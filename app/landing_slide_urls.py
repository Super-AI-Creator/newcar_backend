"""Map legacy hero slide paths saved in DB to current static filenames under frontend/public/images."""

_LEGACY_HERO_SLIDE_URL_MAP: dict[str, str] = {
    "/images/landing_img (1).jpg": "/images/landing-1.jpg",
    "/images/landing_img (2).jpg": "/images/landing-2.jpg",
    "/images/landing_img (3).jpg": "/images/landing-3.jpg",
    "/images/landing_img (4).jpg": "/images/landing-4.jpg",
    "/images/landing-img (1).png": "/images/landing-1.jpg",
    "/images/landing-img (2).png": "/images/landing-2.jpg",
    "/images/landing-img (3).png": "/images/landing-3.jpg",
    "/images/landing-img (4).png": "/images/landing-4.jpg",
}


def normalize_hero_slide_url(url: str) -> str:
    if not isinstance(url, str):
        return url
    u = url.strip()
    return _LEGACY_HERO_SLIDE_URL_MAP.get(u, u)


def normalize_hero_slide_urls_in_payload(payload: dict) -> dict:
    hero = payload.get("hero")
    if not isinstance(hero, dict):
        return payload
    urls = hero.get("slide_urls")
    if not isinstance(urls, list):
        return payload
    out: list = []
    changed = False
    for u in urls:
        if isinstance(u, str):
            nu = normalize_hero_slide_url(u)
            if nu != u:
                changed = True
            out.append(nu)
        else:
            out.append(u)
    if not changed:
        return payload
    return {**payload, "hero": {**hero, "slide_urls": out}}
