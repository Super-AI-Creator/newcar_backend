from app.services.recommendations import compute_vehicle_ranking_score, compute_weighted_score


def test_ranking_scoring():
    scores = {
        "design": 8,
        "performance": 9,
        "technology": 7,
        "practicality": 6,
        "future_value": 5,
    }
    weights = {
        "fun": 1.0,
        "styling": 0.5,
        "performance": 2.0,
        "practical": 1.0,
        "value": 1.5,
    }
    breakdown = compute_weighted_score(scores, weights)
    expected = (
        0.5 * 8 +
        (2.0 + 1.0) * 9 +
        0.0 * 7 +
        1.0 * 6 +
        1.5 * 5
    )
    assert breakdown["total"] == expected


def test_ranking_branch_for_new_and_used():
    new_breakdown = compute_vehicle_ranking_score(
        vehicle_type="new",
        preference_score=30.0,
        max_payment=700.0,
        estimated_monthly=600.0,
        msrp=40000.0,
        effective_price=36000.0,
    )
    used_breakdown = compute_vehicle_ranking_score(
        vehicle_type="used",
        preference_score=30.0,
        max_price=30000.0,
        effective_price=25000.0,
        mileage=40000,
        condition="cpo",
    )

    assert "payment_fit" in new_breakdown
    assert "deal_score" in new_breakdown
    assert "price_fit" in used_breakdown
    assert "mileage_score" in used_breakdown
    assert "condition_score" in used_breakdown
