from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy.exc import OperationalError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import engine
from app.core.deps import get_db
from app.routes.inventory import get_inventory_item
from app.schemas.inventory import InventoryItem
from app.services.make_normalization import canonicalize_make, canonicalize_make_values
from app.services.legacy_tables import load_legacy_tables

router = APIRouter(prefix="/vehicles", tags=["vehicles"])
_FILTERS_CACHE = {"expires_at": 0.0, "data": None}
_FILTERS_TTL_SECONDS = 30.0


def _distinct_non_null_values(db: Session, table, column_name: str):
    column = getattr(table.c, column_name, None)
    if column is None:
        return []
    return [
        row[0]
        for row in db.execute(select(column).where(column.is_not(None)).distinct()).fetchall()
    ]


@router.get("/filters")
def get_vehicle_filters(
    db: Session = Depends(get_db),
):
    now = time.time()
    if _FILTERS_CACHE["data"] is not None and now < _FILTERS_CACHE["expires_at"]:
        return _FILTERS_CACHE["data"]

    try:
        tables = load_legacy_tables(engine)
        listings = tables["vehicle_listings"]

        years = sorted(
            (int(value) for value in _distinct_non_null_values(db, listings, "year")),
            reverse=True,
        )
        vehicle_types = sorted(str(value).lower() for value in _distinct_non_null_values(db, listings, "vehicle_type"))
        conditions = sorted(str(value).lower() for value in _distinct_non_null_values(db, listings, "condition"))
        makes = canonicalize_make_values(_distinct_non_null_values(db, listings, "make"))
        models_by_make = {}
        trims_by_make_model = {}

        make_col = getattr(listings.c, "make", None)
        model_col = getattr(listings.c, "model", None)
        trim_col = getattr(listings.c, "trim", None)
        if make_col is not None and model_col is not None:
            rows = db.execute(
                select(make_col, model_col, trim_col).where(make_col.is_not(None), model_col.is_not(None)).distinct()
            ).fetchall()
            for make_value, model_value, trim_value in rows:
                make_key = canonicalize_make(str(make_value))
                model_key = str(model_value).strip()
                if not make_key or not model_key:
                    continue
                models_by_make.setdefault(make_key, set()).add(model_key)
                if trim_value is not None and str(trim_value).strip():
                    combo_key = f"{make_key}|||{model_key}"
                    trims_by_make_model.setdefault(combo_key, set()).add(str(trim_value).strip())

        models_by_make = {key: sorted(list(values)) for key, values in models_by_make.items()}
        trims_by_make_model = {key: sorted(list(values)) for key, values in trims_by_make_model.items()}
        models = sorted({model for values in models_by_make.values() for model in values})
        trims = sorted({trim for values in trims_by_make_model.values() for trim in values})

        data = {
            "makes": makes,
            "models": models,
            "trims": trims,
            "years": years,
            "vehicle_types": vehicle_types,
            "conditions": conditions,
            "models_by_make": models_by_make,
            "trims_by_make_model": trims_by_make_model,
        }
        _FILTERS_CACHE["data"] = data
        _FILTERS_CACHE["expires_at"] = now + _FILTERS_TTL_SECONDS
        return data
    except OperationalError:
        # If DB briefly drops, return last known filters instead of 500.
        if _FILTERS_CACHE["data"] is not None:
            return _FILTERS_CACHE["data"]
        raise


@router.get("/{vin}", response_model=InventoryItem, response_model_exclude_none=True)
def get_vehicle_by_vin(
    vin: str,
    db: Session = Depends(get_db),
):
    return get_inventory_item(vin=vin, db=db)
