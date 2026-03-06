from datetime import datetime, timezone
from typing import Dict, List, Optional


DEFAULT_TYPE_WEIGHTS = {
    "new": {"preference": 0.45, "payment_fit": 0.25, "deal_score": 0.2, "freshness": 0.1},
    "used": {"preference": 0.4, "price_fit": 0.2, "mileage_score": 0.2, "condition_score": 0.1, "freshness": 0.1},
}


def _normalize_trim(trim: Optional[str]) -> Optional[str]:
    if trim is None:
        return None
    cleaned = str(trim).strip().lower()
    return cleaned or None


def select_model_score_by_fallback(
    candidates: List[object],
    year: Optional[int],
    trim: Optional[str],
):
    requested_trim = _normalize_trim(trim)
    for expected_trim, expected_year in (
        (requested_trim, year),
        (requested_trim, None),
        (None, year),
        (None, None),
    ):
        for candidate in candidates:
            if _normalize_trim(getattr(candidate, "trim", None)) == expected_trim and getattr(candidate, "year", None) == expected_year:
                return candidate
    return None


def compute_weighted_score(scores: Dict[str, int], weights: Dict[str, float]) -> Dict[str, float]:
    mapped = {
        "design": weights.get("styling", 0),
        "performance": weights.get("performance", 0) + weights.get("fun", 0),
        "technology": weights.get("technology", 0),
        "practicality": weights.get("practical", 0),
        "future_value": weights.get("value", 0),
    }

    breakdown = {}
    total = 0.0
    for key, weight in mapped.items():
        value = scores.get(key, 0)
        component = weight * value
        breakdown[key] = component
        total += component
    breakdown["total"] = total
    return breakdown


def freshness_score(last_seen_at: Optional[object]) -> float:
    if not last_seen_at:
        return 0.0
    if isinstance(last_seen_at, str):
        try:
            last_seen_at = datetime.fromisoformat(last_seen_at.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
    if not isinstance(last_seen_at, datetime):
        return 0.0

    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)

    days_old = max((datetime.now(timezone.utc) - last_seen_at).days, 0)
    return max(0.0, 10.0 - min(days_old, 10))


def _safe_ratio_score(actual: Optional[float], cap: Optional[float]) -> float:
    if actual is None or cap is None or cap <= 0:
        return 5.0
    ratio = actual / cap
    if ratio <= 1:
        return max(0.0, 10.0 * (1.0 - (ratio - 0.5) * 0.2))
    return max(0.0, 10.0 - (ratio - 1.0) * 20.0)


def _condition_score(condition: Optional[str]) -> float:
    normalized = str(condition or "").lower()
    if normalized == "cpo":
        return 10.0
    if normalized == "used":
        return 7.0
    if normalized == "new":
        return 9.0
    return 5.0


def compute_vehicle_ranking_score(
    vehicle_type: str,
    preference_score: float,
    max_payment: Optional[float] = None,
    estimated_monthly: Optional[float] = None,
    msrp: Optional[float] = None,
    effective_price: Optional[float] = None,
    max_price: Optional[float] = None,
    mileage: Optional[int] = None,
    condition: Optional[str] = None,
    last_seen_at: Optional[object] = None,
) -> Dict[str, float]:
    vt = str(vehicle_type or "new").lower()
    fresh = freshness_score(last_seen_at)

    if vt == "used":
        price_fit = _safe_ratio_score(effective_price, max_price)
        mileage_score = 10.0 if mileage is None else max(0.0, 10.0 - min(mileage, 200000) / 20000.0)
        condition_score = _condition_score(condition)
        w = DEFAULT_TYPE_WEIGHTS["used"]
        total = (
            preference_score * w["preference"]
            + price_fit * w["price_fit"]
            + mileage_score * w["mileage_score"]
            + condition_score * w["condition_score"]
            + fresh * w["freshness"]
        )
        return {
            "preference": preference_score,
            "price_fit": price_fit,
            "mileage_score": mileage_score,
            "condition_score": condition_score,
            "freshness": fresh,
            "total": total,
        }

    payment_fit = _safe_ratio_score(estimated_monthly, max_payment)
    deal_score = 5.0
    if msrp and msrp > 0 and effective_price is not None:
        discount_ratio = max((msrp - effective_price) / msrp, 0.0)
        deal_score = min(10.0, 5.0 + discount_ratio * 20.0)

    w = DEFAULT_TYPE_WEIGHTS["new"]
    total = (
        preference_score * w["preference"]
        + payment_fit * w["payment_fit"]
        + deal_score * w["deal_score"]
        + fresh * w["freshness"]
    )
    return {
        "preference": preference_score,
        "payment_fit": payment_fit,
        "deal_score": deal_score,
        "freshness": fresh,
        "total": total,
    }
