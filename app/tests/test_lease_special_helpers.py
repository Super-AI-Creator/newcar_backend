from app.routes.inventory import (
    _lease_special_new_price,
    _lease_special_offer_for_response,
    _visible_for_lease_specials,
)


def test_lease_special_new_price_uses_listed_when_msrp_missing():
    assert _lease_special_new_price(msrp_value=None, discounted_value=None, listed_price_value=30095.0) == 30095.0


def test_lease_special_visibility_feed_with_estimate():
    mapping = {"carfax_url": "feed_csv"}
    assert _visible_for_lease_specials(mapping=mapping, offer_out=None, estimated_monthly=499.0) is True
    assert _visible_for_lease_specials(mapping=mapping, offer_out=None, estimated_monthly=None) is False


def test_lease_special_visibility_scraped_requires_offer():
    mapping = {"carfax_url": "https://carfax.example/x"}
    assert _visible_for_lease_specials(mapping=mapping, offer_out=None, estimated_monthly=499.0) is False
    assert (
        _visible_for_lease_specials(
            mapping=mapping,
            offer_out={"monthly_payment": 399.0},
            estimated_monthly=499.0,
        )
        is True
    )


def test_lease_special_offer_for_response_feed_estimate_only():
    mapping = {"carfax_url": "feed_csv"}
    out = _lease_special_offer_for_response(mapping=mapping, offer_out=None, estimated_monthly=512.34)
    assert out == {"monthly_payment": 512.34}
