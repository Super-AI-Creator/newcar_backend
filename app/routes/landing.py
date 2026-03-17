"""Public landing page content (no auth)."""
import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.landing_page_content import LandingPageContent

router = APIRouter(tags=["landing"])


def _default_content() -> dict:
    return {
        "hero": {
            "kicker": "SHOP,  GET APPROVED AND GET THE CAR DELIVERED TO YOUR DOOR WITH A RED BOW",
            "headline": "Buy Any New Car in California Without the Dealership",
            "subtext": "SHOP, GET APPROVED AND GET THE CAR DELIVERED TO YOUR DOOR WITH A RED BOW.",
            "slide_urls": [
                "/images/landing_img (1).jpg",
                "/images/landing_img (2).jpg",
                "/images/landing_img (3).jpg",
                "/images/landing_img (4).jpg",
            ],
            "slide_focus": ["center", "center", "center", "center"],
        },
        "lease": {
            "title": "Current Lease Specials Los Angeles",
            "subtitle": "Shop and compare hundreds of lease offers, if they make it, we have it! 818-705-9200",
        },
        "how_it_works": [
            {"image_url": "/images/hero-cars.jpg", "label": "Browse Statewide Inventory", "image_focus": "center"},
            {"image_url": "/images/deal-1.jpg", "label": "Get Your Best Rate", "image_focus": "center"},
            {"image_url": "/images/landing_img (1).jpg", "label": "Home Delivery With a Bow", "image_focus": "center"},
        ],
    }


@router.get("/landing-page")
def get_landing_page(db: Session = Depends(get_db)):
    row = db.query(LandingPageContent).filter(LandingPageContent.id == 1).first()
    if not row or not row.content or not row.content.strip():
        return _default_content()
    try:
        data = json.loads(row.content)
        return data if isinstance(data, dict) else _default_content()
    except Exception:
        return _default_content()
