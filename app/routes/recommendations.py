from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import engine
from app.core.deps import get_current_user, get_db
from app.models.model_score import ModelScore
from app.models.offer_override import OfferOverride
from app.schemas.recommendations import RecommendationItem, RecommendationResponse, RecommendationExplanation
from app.services.legacy_tables import build_inventory_query, is_feed_csv_listing, serialize_photos
from app.services.payments import estimate_monthly_payment, resolve_price
from app.services.recommendations import compute_vehicle_ranking_score, compute_weighted_score, select_model_score_by_fallback

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/best", response_model=RecommendationResponse)
def best_cars(
    fun: float = Query(0.0),
    styling: float = Query(0.0),
    performance: float = Query(0.0),
    practical: float = Query(0.0),
    value: float = Query(0.0),
    vehicle_type: str = Query("all", pattern="^(new|used|all)$"),
    make: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    max_price: Optional[float] = None,
    max_payment: Optional[float] = None,
    sort_by: str = Query("best", pattern="^(best|price|payment)$"),
    limit: int = 10,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    weights = {
        "fun": fun,
        "styling": styling,
        "performance": performance,
        "practical": practical,
        "value": value,
    }

    base_query = build_inventory_query(
        engine,
        {
            "vehicle_type": vehicle_type,
            "make": make,
            "model": model,
        },
    )
    rows = db.execute(base_query).fetchall()
    if not rows:
        return RecommendationResponse(items=[])

    offers_by_vin: Dict[str, OfferOverride] = {}
    vins = [row.vin for row in rows if getattr(row, "vin", None)]
    if vins:
        offers_by_vin = {
            offer.vin: offer for offer in db.query(OfferOverride).filter(OfferOverride.vin.in_(vins)).all()
        }

    scores_by_make_model: Dict[Tuple[str, str], List[ModelScore]] = defaultdict(list)
    for score in db.query(ModelScore).all():
        if not score.make or not score.model:
            continue
        key = (str(score.make).strip().lower(), str(score.model).strip().lower())
        scores_by_make_model[key].append(score)

    scored_items: List[Tuple[RecommendationItem, Optional[float], Optional[float]]] = []
    for row in rows:
        score: Optional[ModelScore] = None
        if row.make and row.model:
            row_year = int(row.year) if getattr(row, "year", None) is not None else None
            score_key = (str(row.make).strip().lower(), str(row.model).strip().lower())
            score = select_model_score_by_fallback(scores_by_make_model.get(score_key, []), row_year, row.trim)
        if not score:
            continue

        row_vehicle_type = str(getattr(row, "vehicle_type", None) or "new").lower()
        offer = offers_by_vin.get(row.vin)
        discounted = float(offer.discounted_price) if offer and offer.discounted_price is not None else None
        override_monthly = float(offer.monthly_payment) if offer and offer.monthly_payment is not None else None
        msrp = float(row.msrp) if "msrp" in row._fields and row.msrp is not None else None
        listed_price = float(row.listed_price) if "listed_price" in row._fields and row.listed_price is not None else None
        mileage = int(row.mileage) if "mileage" in row._fields and row.mileage is not None else None
        condition = str(row.condition).lower() if "condition" in row._fields and row.condition else None
        price = resolve_price(row_vehicle_type, msrp, discounted, listed_price)
        photos = serialize_photos(
            getattr(row, "photos", None),
            max_photos=None if is_feed_csv_listing(getattr(row, "carfax_url", None)) else 5,
        )
        photo = photos[0] if photos else None
        monthly: Optional[float] = None
        need_monthly_for_sort_or_filter = max_payment is not None or sort_by == "payment"

        if max_price is not None and price is not None and price > max_price:
            continue
        if need_monthly_for_sort_or_filter and price is not None:
            monthly = (
                override_monthly
                if row_vehicle_type == "new" and override_monthly is not None
                else estimate_monthly_payment(price, 5.0, 72, 0.0)
            )
            if max_payment is not None and monthly > max_payment:
                continue

        breakdown = compute_weighted_score(
            {
                "design": score.design,
                "performance": score.performance,
                "technology": score.technology,
                "practicality": score.practicality,
                "future_value": score.future_value,
            },
            weights,
        )
        ranking_breakdown = compute_vehicle_ranking_score(
            vehicle_type=row_vehicle_type,
            preference_score=breakdown["total"],
            max_payment=max_payment,
            estimated_monthly=monthly,
            msrp=msrp,
            effective_price=price,
            max_price=max_price,
            mileage=mileage,
            condition=condition,
            last_seen_at=getattr(row, "last_seen_at", None),
        )

        rec_item = RecommendationItem(
            vin=row.vin,
            vehicle_type=row_vehicle_type,
            make=row.make,
            model=row.model,
            trim=row.trim,
            photo=photo,
            photos=photos,
            score=ranking_breakdown["total"],
            explanation=RecommendationExplanation(
                design=breakdown["design"],
                performance=breakdown["performance"],
                technology=breakdown["technology"],
                practicality=breakdown["practicality"],
                future_value=breakdown["future_value"],
                preference=ranking_breakdown.get("preference"),
                payment_fit=ranking_breakdown.get("payment_fit"),
                deal_score=ranking_breakdown.get("deal_score"),
                price_fit=ranking_breakdown.get("price_fit"),
                mileage_score=ranking_breakdown.get("mileage_score"),
                condition_score=ranking_breakdown.get("condition_score"),
                freshness=ranking_breakdown.get("freshness"),
                total=ranking_breakdown["total"],
            ),
            )

        # Keep derived values for sorting without changing the response schema.
        scored_items.append((rec_item, price, monthly))

    if sort_by == "price":
        scored_items.sort(key=lambda t: t[1] if t[1] is not None else float("inf"))
    elif sort_by == "payment":
        scored_items.sort(key=lambda t: t[2] if t[2] is not None else float("inf"))
    else:
        scored_items.sort(key=lambda t: t[0].score, reverse=True)

    return RecommendationResponse(items=[t[0] for t in scored_items[:limit]])
