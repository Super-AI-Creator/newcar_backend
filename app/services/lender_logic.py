from __future__ import annotations

from typing import Optional

from app.models.lender_rate import LenderRate


def infer_credit_tier(credit_score: Optional[int]) -> str:
    if credit_score is None:
        return "B"
    if credit_score >= 740:
        return "A"
    if credit_score >= 680:
        return "B"
    if credit_score >= 620:
        return "C"
    return "D"


def select_best_rate(
    rows: list[LenderRate],
    tier: str,
    vehicle_type: Optional[str] = None,
) -> Optional[LenderRate]:
    normalized_tier = (tier or "B").strip().upper()
    normalized_type = (vehicle_type or "all").strip().lower()

    scoped = [
        row
        for row in rows
        if (row.credit_tier or "").strip().upper() == normalized_tier
        and ((row.vehicle_type or "all").strip().lower() in {"all", normalized_type})
    ]
    if not scoped:
        scoped = [row for row in rows if (row.credit_tier or "").strip().upper() == normalized_tier]
    if not scoped:
        return None

    return sorted(scoped, key=lambda row: (float(row.apr), -(row.max_term_months or 0)))[0]
