from typing import Optional

from app.models.offer_override import OfferOverride


def _clean_float(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return float(value)


def _clean_int(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return int(value)
    except Exception:
        return None


def apply_offer_visibility(offer: Optional[OfferOverride], vehicle_type: Optional[str] = None):
    if not offer:
        return None

    out = {}
    down_payment = _clean_float(offer.down_payment)
    monthly_payment = _clean_float(offer.monthly_payment)
    discounted_price = _clean_float(offer.discounted_price)
    term_months = _clean_int(offer.term_months)
    miles_per_year = _clean_int(offer.miles_per_year)

    if down_payment is not None:
        out["down_payment"] = down_payment
    if monthly_payment is not None:
        out["monthly_payment"] = monthly_payment
    if discounted_price is not None:
        out["discounted_price"] = discounted_price
    if term_months is not None and term_months > 0:
        out["term_months"] = term_months
    if miles_per_year is not None and miles_per_year > 0:
        out["miles_per_year"] = miles_per_year

    return out or None


def set_offer_visibility(offer: OfferOverride) -> None:
    offer.visible_down_payment = offer.down_payment is not None
    offer.visible_monthly = offer.monthly_payment is not None
    offer.visible_discounted = offer.discounted_price is not None
