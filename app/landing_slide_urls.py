"""Map legacy landing image paths saved in DB to current filenames under frontend/public/images."""

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
    """Normalize hero.slide_urls and how_it_works[].image_url (CMS often reuses slide paths)."""
    out = payload
    hero = out.get("hero")
    if isinstance(hero, dict):
        urls = hero.get("slide_urls")
        if isinstance(urls, list):
            slide_out: list = []
            slide_changed = False
            for u in urls:
                if isinstance(u, str):
                    nu = normalize_hero_slide_url(u)
                    if nu != u:
                        slide_changed = True
                    slide_out.append(nu)
                else:
                    slide_out.append(u)
            if slide_changed:
                out = {**out, "hero": {**hero, "slide_urls": slide_out}}
                hero = out["hero"]

    how = out.get("how_it_works")
    if not isinstance(how, list):
        return out
    new_how: list = []
    how_changed = False
    for item in how:
        if not isinstance(item, dict):
            new_how.append(item)
            continue
        url = item.get("image_url")
        if isinstance(url, str):
            nu = normalize_hero_slide_url(url)
            if nu != url:
                how_changed = True
                new_how.append({**item, "image_url": nu})
            else:
                new_how.append(item)
        else:
            new_how.append(item)
    if how_changed:
        out = {**out, "how_it_works": new_how}
    return out
