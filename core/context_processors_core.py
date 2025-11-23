# core/context_processors_core.py
from django.conf import settings
from django.urls import resolve, reverse

from core.services.media import DEFAULT_MEDIA_CAPTION, resolve_media_asset

from .models import HeroImage

# Default static fallbacks for every public route that expects a hero.
DEFAULT_CAPTION = DEFAULT_MEDIA_CAPTION
HERO_FALLBACKS = {
    "home": {"path": "img/hero-home.jpg", "alt": "Home hero"},
    "client-dashboard": {"path": "img/hero-services.jpg", "alt": "Services hero"},
    "store": {"path": "img/hero-products.jpg", "alt": "Products hero"},
    "merch": {"path": "img/hero-merch.jpg", "alt": "Merch hero"},
    "dealer-status": {"path": "img/hero-dealers.jpg", "alt": "Dealer banner"},
    "financing": {"path": "img/hero-financing.jpg", "alt": "Financing hero"},
    "our-story": {"path": "img/hero-about.jpg", "alt": "About hero"},
    "services-brake-suspension": {
        "path": "img/hero-services.jpg",
        "alt": "Brake & Suspension hero",
    },
}
FALLBACK = {"path": "img/hero-preview.png", "alt": "BGM hero"}

# Bind URL names to HeroImage placements for DB lookups.
HERO_DB_BINDINGS = {
    "home": HeroImage.Location.HOME,
    "dealer-status": HeroImage.Location.DEALER_STATUS,
    "store": HeroImage.Location.STORE,
    "merch": HeroImage.Location.MERCH,
    "services-brake-suspension": HeroImage.Location.BRAKE_SUSPENSION_HERO,
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
    location_key = HERO_DB_BINDINGS.get(url_name)
    payload = resolve_media_asset(
        location_key,
        defaults["path"],
        defaults.get("alt") or f"BGM — {url_name or 'preview'}",
        defaults.get("caption", DEFAULT_CAPTION),
    )
    payload["location"] = url_name or payload.get("location", "")
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

    level = profile.get_dealer_tier_level()
    label = level.label if level else profile.get_dealer_tier_display()
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


def marketing_tags(request):
    """
    Provides consistent marketing metadata + tracking IDs to every template.
    Keeps logic centralized so templates only worry about rendering.
    """
    config = getattr(settings, "MARKETING", {})
    site_name = config.get("site_name") or "BGM Customs"
    default_description = config.get("default_description") or ""
    default_image = config.get("default_image") or "/static/img/bad-guy-preview.png"
    organization_logo = config.get("organization_logo") or default_image
    origin = ""
    canonical_url = ""
    page_url = ""

    if request is not None:
        try:
            origin = request.build_absolute_uri("/")
        except Exception:
            origin = ""
        else:
            origin = origin.rstrip("/")
        try:
            canonical_url = request.build_absolute_uri(request.path)
        except Exception:
            canonical_url = ""
        try:
            page_url = request.build_absolute_uri()
        except Exception:
            page_url = canonical_url

    def _absolute(url: str, fallback: str = "") -> str:
        candidate = url or fallback
        if not candidate:
            return ""
        if candidate.startswith(("http://", "https://")):
            return candidate
        if origin:
            return f"{origin}{candidate}"
        return candidate

    default_image_absolute = _absolute(default_image)
    organization_logo_absolute = _absolute(organization_logo, default_image)

    return {
        "marketing": {
            "site_name": site_name,
            "tagline": config.get("tagline") or "",
            "default_description": default_description,
            "default_image": default_image,
            "default_image_absolute": default_image_absolute,
            "organization_logo": organization_logo,
            "organization_logo_absolute": organization_logo_absolute,
            "organization_same_as": config.get("organization_same_as") or [],
            "canonical_url": canonical_url,
            "page_url": page_url or canonical_url,
            "origin": origin,
            "google_tag_manager_id": config.get("google_tag_manager_id") or "",
            "google_ads_id": config.get("google_ads_id") or "",
            "google_ads_conversion_label": config.get("google_ads_conversion_label") or "",
            "google_ads_send_page_view": config.get("google_ads_send_page_view", True),
        }
    }


def currency(request):
    """
    Expose default currency code/symbol to every template (storefront, dealer portal, etc).
    """
    return {
        "currency": {
            "code": getattr(settings, "DEFAULT_CURRENCY_CODE", "CAD"),
            "symbol": getattr(settings, "DEFAULT_CURRENCY_SYMBOL", "$"),
        }
    }
