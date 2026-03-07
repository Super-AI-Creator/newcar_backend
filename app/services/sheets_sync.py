from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from google.oauth2 import service_account
from googleapiclient.discovery import build
import httplib2
from google_auth_httplib2 import AuthorizedHttp
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import engine
from app.models.model_score import ModelScore
from app.models.offer_override import OfferOverride
from app.models.sheet_sources_meta import SheetSourceMeta
from app.models.enums import OfferSource
from app.services.legacy_tables import build_inventory_query
from app.services.make_normalization import canonicalize_make, normalize_text_token


SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
GOOGLE_API_TIMEOUT_SECONDS = 30

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

    # Bound request time to avoid indefinite UI loading states on slow/unreachable Google API calls.
    authed_http = AuthorizedHttp(creds, http=httplib2.Http(timeout=GOOGLE_API_TIMEOUT_SECONDS))
    return build("sheets", "v4", http=authed_http, cache_discovery=False)


def _parse_service_account_info(raw: str) -> Optional[dict]:
    # 1) Raw JSON string
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # 2) Base64-encoded JSON string (standard or URL-safe)
    compact = "".join(raw.split())
    padded = compact + ("=" * (-len(compact) % 4))
    for decoder in (
        lambda value: base64.b64decode(value, validate=True),
        base64.urlsafe_b64decode,
    ):
        try:
            decoded = decoder(padded).decode("utf-8")
            parsed = json.loads(decoded)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue

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
    inventory_index = _build_inventory_index(db)

    resolved_by_vin: dict[str, tuple[Optional[float], Optional[float], Optional[float], Optional[int], Optional[int]]] = {}

    for row in data_rows:
        row_dict = {header[i]: row[i] if i < len(row) else None for i in range(len(header))}
        year = _to_optional_int(row_dict.get("year"))
        make = canonicalize_make((row_dict.get("make") or "").strip())
        model = (row_dict.get("model") or "").strip()
        msrp = _to_decimal(row_dict.get("discounted_price"))
        down_payment = _to_decimal(row_dict.get("down_payment"))
        monthly_payment = _to_decimal(row_dict.get("monthly_payment"))
        term_months = _to_optional_int(row_dict.get("term_months"))
        miles_per_year = _to_optional_int(row_dict.get("miles_per_year"))

        # Lease Specials sync is driven by sheet Year/Make/Model rows.
        # VIN column is intentionally ignored here.
        if not (year and make and model):
            continue
        target_vins = _match_vins_from_inventory_index(
            inventory_index,
            year=year,
            make=make,
            model=model,
        )

        if not target_vins:
            continue

        unique_vins = sorted(set(target_vins))
        for matched_vin in unique_vins:
            matched_vin_key = str(matched_vin).strip().upper()
            # If a VIN appears more than once, keep the last sheet row value.
            resolved_by_vin[matched_vin_key] = (down_payment, monthly_payment, msrp, term_months, miles_per_year)

    payload_rows = []
    for vin, (down_payment, monthly_payment, discounted_price, term_months, miles_per_year) in resolved_by_vin.items():
        payload_rows.append(
            {
                "vin": vin,
                "down_payment": down_payment,
                "monthly_payment": monthly_payment,
                "discounted_price": discounted_price,
                "term_months": term_months,
                "miles_per_year": miles_per_year,
                "visible_down_payment": down_payment is not None,
                "visible_monthly": monthly_payment is not None,
                "visible_discounted": discounted_price is not None,
                "source": OfferSource.sheet,
            }
        )

    _bulk_upsert_offer_overrides(db, payload_rows)
    count = len(payload_rows)

    _upsert_meta(db, "offers", settings.offers_sheet_id, settings.offers_sheet_tab, row_hash, None)
    db.commit()
    return count, row_hash


def _build_inventory_index(db: Session) -> dict[tuple[int, str, str], list[tuple[str, Optional[float]]]]:
    rows = db.execute(build_inventory_query(engine, {"vehicle_type": "all"})).fetchall()
    index: dict[tuple[int, str, str], list[tuple[str, Optional[float]]]] = {}
    for row in rows:
        mapping = row._mapping
        vin = mapping.get("vin")
        year_raw = mapping.get("year")
        make_raw = mapping.get("make")
        model_raw = mapping.get("model")
        if not vin or year_raw is None or not make_raw or not model_raw:
            continue

        try:
            year = int(year_raw)
        except Exception:
            continue

        make = canonicalize_make(str(make_raw).strip())
        model = str(model_raw).strip()
        if not make or not model:
            continue

        msrp_raw = mapping.get("msrp")
        msrp: Optional[float] = None
        if msrp_raw is not None:
            try:
                msrp = float(msrp_raw)
            except Exception:
                msrp = None

        key = (year, normalize_text_token(make), normalize_text_token(model))
        index.setdefault(key, []).append((str(vin).strip().upper(), msrp))
    return index


def _match_vins_from_inventory_index(
    index: dict[tuple[int, str, str], list[tuple[str, Optional[float]]]],
    *,
    year: int,
    make: str,
    model: str,
) -> list[str]:
    key = (year, normalize_text_token(make), normalize_text_token(model))
    candidates = index.get(key, [])
    if not candidates:
        return []
    return [vin for vin, _ in candidates]


def _bulk_upsert_offer_overrides(db: Session, rows: list[dict]) -> None:
    if not rows:
        return

    table = OfferOverride.__table__
    chunk_size = 500
    for idx in range(0, len(rows), chunk_size):
        chunk = rows[idx : idx + chunk_size]
        stmt = mysql_insert(table).values(chunk)
        upsert_stmt = stmt.on_duplicate_key_update(
            down_payment=stmt.inserted.down_payment,
            monthly_payment=stmt.inserted.monthly_payment,
            discounted_price=stmt.inserted.discounted_price,
            term_months=stmt.inserted.term_months,
            miles_per_year=stmt.inserted.miles_per_year,
            visible_down_payment=stmt.inserted.visible_down_payment,
            visible_monthly=stmt.inserted.visible_monthly,
            visible_discounted=stmt.inserted.visible_discounted,
            source=stmt.inserted.source,
            updated_at=datetime.utcnow(),
        )
        db.execute(upsert_stmt)


def sync_scores(db: Session) -> Tuple[int, str]:
    rows = _fetch_sheet(settings.scores_sheet_id, settings.scores_sheet_tab)
    if not rows:
        return 0, "no rows"

    header = [_canonical_header(h) for h in rows[0]]
    data_rows = rows[1:]
    row_hash = _hash_rows(data_rows)

    parsed_rows: list[tuple[str, str, Optional[str], Optional[int], int, int, int, int, int]] = []
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

        parsed_rows.append(
            (
                make,
                model,
                trim,
                year,
                _to_int(row_dict.get("design")),
                _to_int(row_dict.get("performance")),
                _to_int(row_dict.get("technology")),
                _to_int(row_dict.get("practicality")),
                _to_int(row_dict.get("future_value")),
            )
        )

    existing_scores = db.query(ModelScore).all()
    score_map: dict[tuple[str, str, Optional[str], Optional[int]], ModelScore] = {
        (row.make, row.model, row.trim, row.year): row for row in existing_scores
    }

    for make, model, trim, year, design, performance, technology, practicality, future_value in parsed_rows:
        key = (make, model, trim, year)
        score = score_map.get(key)
        if not score:
            score = ModelScore(make=make, model=model, trim=trim, year=year)
            db.add(score)
            score_map[key] = score
        score.design = design
        score.performance = performance
        score.technology = technology
        score.practicality = practicality
        score.future_value = future_value

    count = len(parsed_rows)

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
