from typing import Optional


def estimate_monthly_payment(price: float, apr: float, term_months: int, down: float) -> float:
    principal = max(price - down, 0)
    monthly_rate = (apr / 100) / 12
    if monthly_rate == 0:
        return principal / term_months
    return principal * (monthly_rate * (1 + monthly_rate) ** term_months) / ((1 + monthly_rate) ** term_months - 1)


def resolve_price(
    vehicle_type: Optional[str],
    msrp: Optional[float],
    discounted_price: Optional[float],
    listed_price: Optional[float] = None,
) -> Optional[float]:
    if str(vehicle_type or "").lower() == "used":
        return listed_price
    if discounted_price is not None:
        return discounted_price
    return msrp
