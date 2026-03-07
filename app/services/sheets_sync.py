from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from google.oauth2 import service_account
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import engine
from app.models.model_score import ModelScore
from app.models.offer_override import OfferOverride
from app.models.sheet_sources_meta import SheetSourceMeta
from app.models.enums import OfferSource
from app.services.legacy_tables import build_inventory_query
from app.services.make_normalization import canonicalize_make, normalize_text_token
from app.services.offers import set_offer_visibility


SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

HEADER_ALIASES = {
    "vin": {"vin", "listing id", "listing_id"},
    "down_payment": {"down_payment", "down payment", "lease down payment", "add to msrp"},
    "monthly_payment": {"monthly_payment", "monthly payment", "lease payment"},
    "term_months": {"term", "term months", "lease term"},
    "miles_per_year": {"miles / year", "miles/year", "miles per year", "mile per year"},
    "discounted_price": {
        "discounted_price",
        "discounted price",
        "selling price: add $500 to cost",
        "selling price add $500 to cost",
        "price",
        "msrp",
    },
    "make": {"make"},
    "model": {"model"},
    "trim": {"trim"},
    "year": {"year"},
    "design": {"design", "design (1-10)"},
    "performance": {"performance", "performance (1-10)"},
    "technology": {"technology", "technology (1-10)"},
    "practicality": {"practicality", "practicality (1-10)"},
    "future_value": {"future_value", "future value", "future value (1-10)"},
}


def _normalize_header(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def _canonical_header(value: str) -> str:
    normalized = _normalize_header(value)
    for canonical, aliases in HEADER_ALIASES.items():
        if normalized in aliases:
            return canonical
    return normalized


def _get_sheets_service():
    raw = (settings.google_service_account_json or "").strip()
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set.")

    normalized = raw.strip("\"'")

    # Prefer inline JSON/base64 first; only then attempt filesystem path.
    info = _parse_service_account_info(normalized)
    if info is not None:
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        candidate_path = _safe_existing_path(normalized)
        if not candidate_path:
            raise RuntimeError(
                "GOOGLE_SERVICE_ACCOUNT_JSON must be either: "
                "(a) existing file path, (b) raw JSON object string, or (c) base64-encoded JSON object."
            )
        creds = service_account.Credentials.from_service_account_file(str(candidate_path), scopes=SCOPES)

    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _parse_service_account_info(raw: str) -> Optional[dict]:
    # 1) Raw JSON string
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # 2) Base64-encoded JSON string
    try:
        compact = "".join(raw.split())
        padded = compact + ("=" * (-len(compact) % 4))
        decoded = base64.b64decode(padded, validate=True).decode("utf-8")
        parsed = json.loads(decoded)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    return None


def _safe_existing_path(raw: str) -> Optional[Path]:
    try:
        candidate_path = Path(raw).expanduser()
        if candidate_path.exists():
            return candidate_path
    except OSError:
        # Inputs like long base64 blobs are not valid file names.
        return None
    return None


def _hash_rows(rows: List[List[str]]) -> str:
    joined = "\n".join(["|".join([str(c).strip() for c in row]) for row in rows])
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _fetch_sheet(sheet_id: str, tab: str) -> List[List[str]]:
    service = _get_sheets_service()
    result = service.spreadsheets().values().get(spreadsheetId=sheet_id, range=tab).execute()
    return result.get("values", [])


def sync_offers(db: Session) -> Tuple[int, str]:
    rows = _fetch_sheet(settings.offers_sheet_id, settings.offers_sheet_tab)
    if not rows:
        return 0, "no rows"

    header = [_canonical_header(h) for h in rows[0]]
    data_rows = rows[1:]
    row_hash = _hash_rows(data_rows)

    count = 0
    for row in data_rows:
        row_dict = {header[i]: row[i] if i < len(row) else None for i in range(len(header))}
        vin = (row_dict.get("vin") or "").strip()
        year = _to_optional_int(row_dict.get("year"))
        make = canonicalize_make((row_dict.get("make") or "").strip())
        model = (row_dict.get("model") or "").strip()
        msrp = _to_decimal(row_dict.get("discounted_price"))
        down_payment = _to_decimal(row_dict.get("down_payment"))
        monthly_payment = _to_decimal(row_dict.get("monthly_payment"))
        term_months = _to_optional_int(row_dict.get("term_months"))
        miles_per_year = _to_optional_int(row_dict.get("miles_per_year"))

        target_vins: list[str] = []
        if vin:
            target_vins = [vin]
        elif year and make and model:
            target_vins = _match_vins_by_year_make_model(db, year=year, make=make, model=model, msrp=msrp)

        if not target_vins:
            continue

        for matched_vin in sorted(set(target_vins)):
            offer = db.query(OfferOverride).filter(OfferOverride.vin == matched_vin).first()
            if not offer:
                offer = OfferOverride(vin=matched_vin, source=OfferSource.sheet)
                db.add(offer)
            offer.down_payment = down_payment
            offer.monthly_payment = monthly_payment
            # New sheet provides MSRP; keep mapping in discounted_price so lease-special cards can use it.
            offer.discounted_price = msrp
            offer.term_months = term_months
            offer.miles_per_year = miles_per_year
            offer.source = OfferSource.sheet
            set_offer_visibility(offer)
            count += 1

    _upsert_meta(db, "offers", settings.offers_sheet_id, settings.offers_sheet_tab, row_hash, None)
    db.commit()
    return count, row_hash


def sync_scores(db: Session) -> Tuple[int, str]:
    rows = _fetch_sheet(settings.scores_sheet_id, settings.scores_sheet_tab)
    if not rows:
        return 0, "no rows"

    header = [_canonical_header(h) for h in rows[0]]
    data_rows = rows[1:]
    row_hash = _hash_rows(data_rows)

    count = 0
    for row in data_rows:
        row_dict = {header[i]: row[i] if i < len(row) else None for i in range(len(header))}
        make = (row_dict.get("make") or "").strip()
        model = (row_dict.get("model") or "").strip()
        trim = (row_dict.get("trim") or "").strip() or None
        year = _to_optional_int(row_dict.get("year"))
        if not make or not model:
            continue

        def _to_int(v):
            try:
                return int(float(v))
            except Exception:
                return 0

        score_query = db.query(ModelScore).filter(
            ModelScore.make == make,
            ModelScore.model == model,
            ModelScore.trim == trim,
        )
        if year is None:
            score_query = score_query.filter(ModelScore.year.is_(None))
        else:
            score_query = score_query.filter(ModelScore.year == year)
        score = score_query.first()
        if not score:
            score = ModelScore(make=make, model=model, trim=trim, year=year)
            db.add(score)
        else:
            score.year = year
        score.design = _to_int(row_dict.get("design"))
        score.performance = _to_int(row_dict.get("performance"))
        score.technology = _to_int(row_dict.get("technology"))
        score.practicality = _to_int(row_dict.get("practicality"))
        score.future_value = _to_int(row_dict.get("future_value"))
        count += 1

    _upsert_meta(db, "scores", settings.scores_sheet_id, settings.scores_sheet_tab, row_hash, None)
    db.commit()
    return count, row_hash


def _upsert_meta(db: Session, name: str, sheet_id: str, tab: str, row_hash: str, error: Optional[str]):
    meta = (
        db.query(SheetSourceMeta)
        .filter(SheetSourceMeta.sheet_name == name, SheetSourceMeta.sheet_id == sheet_id, SheetSourceMeta.tab_name == tab)
        .first()
    )
    if not meta:
        meta = SheetSourceMeta(sheet_name=name, sheet_id=sheet_id, tab_name=tab)
        db.add(meta)
    meta.last_synced_at = datetime.utcnow()
    meta.last_row_hash = row_hash
    meta.last_error = error


def _to_optional_int(v) -> Optional[int]:
    if v is None:
        return None
    text = str(v).strip()
    if text == "":
        return None
    if text.lower() in {"call", "n/a", "na", "-"}:
        return None
    try:
        return int(float(text))
    except Exception:
        return None


def _to_decimal(v) -> Optional[float]:
    if v is None:
        return None
    text = str(v).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"call", "n/a", "na", "-"}:
        return None
    cleaned = (
        text.replace("$", "")
        .replace(",", "")
        .replace(" ", "")
    )
    try:
        return float(cleaned)
    except ValueError:
        return None


def _match_vins_by_year_make_model(
    db: Session,
    *,
    year: int,
    make: str,
    model: str,
    msrp: Optional[float],
) -> list[str]:
    query = build_inventory_query(
        engine,
        {
            "vehicle_type": "all",
            "year": year,
            "make": make,
            "model": model,
        },
    )
    rows = db.execute(query).fetchall()
    if not rows:
        return []

    if msrp is None:
        return [str(row._mapping.get("vin")) for row in rows if row._mapping.get("vin")]

    normalized_model = normalize_text_token(model)
    matched_vins: list[str] = []
    for row in rows:
        mapping = row._mapping
        vin = mapping.get("vin")
        if not vin:
            continue
        row_model = normalize_text_token(str(mapping.get("model") or ""))
        if row_model and row_model != normalized_model:
            continue
        row_msrp = mapping.get("msrp")
        if row_msrp is None:
            continue
        try:
            row_msrp_float = float(row_msrp)
        except Exception:
            continue
        # Allow small feed variance around MSRP formatting/rounding.
        if abs(row_msrp_float - msrp) <= 250:
            matched_vins.append(str(vin))

    if matched_vins:
        return matched_vins

    # If no MSRP match found, fall back to year+make+model so we still apply lease rows.
    return [str(row._mapping.get("vin")) for row in rows if row._mapping.get("vin")]
