# core/context_processors_core.py
from django.urls import resolve, reverse
from django.templatetags.static import static

from .models import HeroImage

# Default static fallbacks for every public route that expects a hero.
DEFAULT_CAPTION = "Product may not appear exactly as shown."
HERO_FALLBACKS = {
    "home": {"path": "img/hero-home.jpg", "alt": "Home hero"},
    "client-dashboard": {"path": "img/hero-services.jpg", "alt": "Services hero"},
    "store": {"path": "img/hero-products.jpg", "alt": "Products hero"},
    "merch": {"path": "img/hero-merch.jpg", "alt": "Merch hero"},
    "dealer-status": {"path": "img/hero-dealers.jpg", "alt": "Dealer banner"},
    "financing": {"path": "img/hero-financing.jpg", "alt": "Financing hero"},
    "our-story": {"path": "img/hero-about.jpg", "alt": "About hero"},
}
FALLBACK = {"path": "img/hero-preview.png", "alt": "BGM hero"}

# Bind URL names to HeroImage placements for DB lookups.
HERO_DB_BINDINGS = {
    "home": HeroImage.Location.HOME,
    "dealer-status": HeroImage.Location.DEALER_STATUS,
    "store": HeroImage.Location.STORE,
    "merch": HeroImage.Location.MERCH,
}


def _resolve_url_name(request) -> str:
    try:
        match = resolve(request.path_info)
        return match.url_name or ""
    except Exception:
        return ""


def hero_media(request):
    url_name = _resolve_url_name(request)
    defaults = HERO_FALLBACKS.get(url_name, FALLBACK)
    payload = {
        "src": static(defaults["path"]),
        "alt": defaults.get("alt") or f"BGM — {url_name or 'preview'}",
        "caption": defaults.get("caption", DEFAULT_CAPTION),
        "location": url_name,
        "is_custom": False,
    }

    location_key = HERO_DB_BINDINGS.get(url_name)
    if location_key:
        try:
            hero = (
                HeroImage.objects.filter(location=location_key, is_active=True)
                .exclude(image="")
                .first()
            )
        except Exception:
            hero = None
        if hero and hero.image:
            try:
                payload.update(
                    {
                        "src": hero.image.url,
                        "alt": hero.alt_text or hero.title or hero.get_location_display(),
                        "caption": hero.caption or DEFAULT_CAPTION,
                        "is_custom": True,
                    }
                )
            except Exception:
                pass

    return {"hero_media": payload}


def dealer_portal(request):
    """
    Lightweight context that exposes dealer status, tier label, and discount percent across templates.
    """
    data = {
        "is_dealer": False,
        "tier_code": "NONE",
        "tier_label": "Standard access",
        "discount_percent": 0,
        "dealer_since": None,
        "show_discount": False,
        "url": reverse("dealer-status"),
    }

    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"dealer_portal": data}

    try:
        profile = user.userprofile
    except Exception:
        return {"dealer_portal": data}

    label = profile.get_dealer_tier_display()
    discount = profile.dealer_discount_percent
    data.update(
        {
            "is_dealer": bool(profile.is_dealer),
            "tier_code": profile.dealer_tier,
            "tier_label": label or "Dealer",
            "discount_percent": discount,
            "dealer_since": profile.dealer_since,
            "show_discount": bool(profile.is_dealer and discount),
        }
    )
    return {"dealer_portal": data}
