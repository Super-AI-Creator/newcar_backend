"""Public landing page content (no auth)."""
import json
import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.landing_footer_defaults import FOOTER_DISCLOSURE_DEFAULT
from app.landing_slide_urls import normalize_hero_slide_urls_in_payload
from app.models.landing_page_content import LandingPageContent

router = APIRouter(tags=["landing"])
_LANDING_CACHE: dict[str, tuple[float, dict]] = {}
_LANDING_CACHE_TTL_SECONDS = 60.0


def invalidate_landing_page_cache() -> None:
    _LANDING_CACHE.clear()


def _default_hero_falling() -> dict:
    return {
        "enabled": True,
        "phrases": [
            "The #1 Dealer Site",
            "It's Very Easy",
            "Shop From Home",
            "Delivered to Your Door",
            "Licensed Auto Broker",
            "Red Bow Delivery",
            "Fast & Painless",
            "Statewide Inventory",
        ],
        "duration_min": 19,
        "duration_max": 26,
        "max_phrases": 8,
        "stagger": 2.4,
    }


def _default_content() -> dict:
    return {
        "hero": {
            "kicker": "SHOP,  GET APPROVED AND GET THE CAR DELIVERED TO YOUR DOOR WITH A RED BOW",
            "headline": "Buy Any New Car in California Without the Dealership",
            "subtext": "SHOP, GET APPROVED AND GET THE CAR DELIVERED TO YOUR DOOR WITH A RED BOW.",
            "slide_urls": [
                "/images/landing-1.jpg",
                "/images/landing-2.jpg",
                "/images/landing-3.jpg",
                "/images/landing-4.jpg",
            ],
            "slide_focus": ["center", "center", "center", "center"],
            "falling": _default_hero_falling(),
        },
        "lease": {
            "title": "Current Lease Specials Los Angeles",
            "subtitle": "Shop and compare hundreds of lease offers, if they make it, we have it! 818-705-9200",
        },
        "how_it_works": [
            {"image_url": "/images/hero-cars.jpg", "label": "Browse Statewide Inventory", "image_focus": "center"},
            {"image_url": "/images/deal-1.jpg", "label": "Get Your Best Rate", "image_focus": "center"},
            {"image_url": "/images/panel-cars.jpg", "label": "Home Delivery With a Bow", "image_focus": "center"},
        ],
        "footer": {
            "facebook_url": "https://www.facebook.com/newcarsuperstore/",
            "twitter_url": "https://twitter.com/autobrokerla",
            "google_plus_url": "https://plus.google.com/101810114903929491113",
            "instagram_url": "https://www.instagram.com/newcarsuperstore/",
            "youtube_url": "https://www.youtube.com/channel/UCfnPH7n_x1cHc5WXDb0zMJQ",
            "address_line": "2671 Ventura Blvd Suite Oxnard CA 93036",
            "phone_line": "818.705.9200, 818.705.9202",
            "footer_disclosure": FOOTER_DISCLOSURE_DEFAULT,
            "copyright_line": "",
            "link_lease_label": "Lease Specials Los Angeles",
            "link_lease_url": "/lease-specials",
            "link_broker_label": "Auto Broker Los Angeles",
            "link_broker_url": "/most-reviewed-auto-broker-los-angeles",
        },
    }


@router.get("/landing-page")
def get_landing_page(db: Session = Depends(get_db)):
    cache_key = "landing-page"
    now = time.time()
    cached = _LANDING_CACHE.get(cache_key)
    if cached:
        expires_at, payload = cached
        if now < expires_at:
            return payload

    row = db.query(LandingPageContent).filter(LandingPageContent.id == 1).first()
    if not row or not row.content or not row.content.strip():
        payload = normalize_hero_slide_urls_in_payload(_default_content())
        _LANDING_CACHE[cache_key] = (now + _LANDING_CACHE_TTL_SECONDS, payload)
        return payload
    try:
        data = json.loads(row.content)
        payload = data if isinstance(data, dict) else _default_content()
    except Exception:
        payload = _default_content()
    foot = payload.get("footer")
    if isinstance(foot, dict) and not (str(foot.get("footer_disclosure") or "").strip()):
        payload = {
            **payload,
            "footer": {**foot, "footer_disclosure": FOOTER_DISCLOSURE_DEFAULT},
        }
    hero = payload.get("hero")
    if isinstance(hero, dict) and not isinstance(hero.get("falling"), dict):
        payload = {**payload, "hero": {**hero, "falling": _default_hero_falling()}}
    payload = normalize_hero_slide_urls_in_payload(payload)
    _LANDING_CACHE[cache_key] = (now + _LANDING_CACHE_TTL_SECONDS, payload)
    return payload
