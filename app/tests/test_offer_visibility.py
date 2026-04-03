from app.models.offer_override import OfferOverride
from app.services.offers import apply_offer_visibility


def test_offer_visibility_rule_new_only_non_blank_fields():
    offer = OfferOverride(down_payment=None, monthly_payment=250.0, discounted_price=None)
    result = apply_offer_visibility(offer, "new")
    assert "down_payment" not in result
    assert result["monthly_payment"] == 250.0
    assert "discounted_price" not in result


def test_offer_visibility_visible_for_used():
    offer = OfferOverride(down_payment=500.0, monthly_payment=250.0, discounted_price=22000.0)
    result = apply_offer_visibility(offer, "used")
    assert result["down_payment"] == 500.0
    assert result["monthly_payment"] == 250.0
    assert result["discounted_price"] == 22000.0


def test_offer_visibility_lease_special_requires_monthly():
    offer = OfferOverride(down_payment=None, monthly_payment=None, discounted_price=42000.0)
    assert apply_offer_visibility(offer, "new", require_monthly_payment=False) is not None
    assert apply_offer_visibility(offer, "new", require_monthly_payment=True) is None
    offer2 = OfferOverride(down_payment=1000.0, monthly_payment=399.0, discounted_price=None)
    out = apply_offer_visibility(offer2, "new", require_monthly_payment=True)
    assert out is not None
    assert out["monthly_payment"] == 399.0
