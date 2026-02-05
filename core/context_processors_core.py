# core/context_processors_core.py
from django.conf import settings
from django.urls import resolve, reverse

from core.services.media import (
    DEFAULT_MEDIA_CAPTION,
    build_home_hero_carousel,
    resolve_media_asset,
)

from .models import HeroImage, TopbarSettings, HomePageCopy, ServicesPageCopy, StorePageCopy
from core.services.fonts import serialize_font_preset

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
    "services-electrical-work": {
        "path": "img/hero-services.jpg",
        "alt": "Electrical Work hero",
    },
    "services-performance-tuning": {
        "path": "img/hero-services.jpg",
        "alt": "Performance Tuning hero",
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
    "services-electrical-work": HeroImage.Location.ELECTRICAL_WORK_HERO,
    "services-performance-tuning": HeroImage.Location.PERFORMANCE_TUNING_HERO,
}


PREVIEW_MODEL_URLS = {
    "HomePageCopy": "home",
    "ServicesPageCopy": "client-dashboard",
    "StorePageCopy": "store",
    "MerchPageCopy": "merch",
    "FinancingPageCopy": "financing",
    "AboutPageCopy": "our-story",
    "ClientPortalPageCopy": "client-portal",
    "DealerStatusPageCopy": "dealer-status",
}

PAGE_BACKGROUND_MODELS = {
    "home": HomePageCopy,
    "client-dashboard": ServicesPageCopy,
    "store": StorePageCopy,
}


def _resolve_url_name(request) -> str:
    preview_model = getattr(request, "pagecopy_preview_model", None)
    if preview_model:
        url_name = PREVIEW_MODEL_URLS.get(preview_model.__name__)
        if url_name:
            return url_name
    try:
        match = resolve(request.path_info)
        return match.url_name or ""
    except Exception:
        return ""


def hero_media(request):
    url_name = _resolve_url_name(request)
    defaults = HERO_FALLBACKS.get(url_name, FALLBACK)
    location_key = HERO_DB_BINDINGS.get(url_name)

    page_asset = None
    page_model = PAGE_BACKGROUND_MODELS.get(url_name)
    if page_model:
        try:
            page_copy = page_model.get_solo()
            candidate = getattr(page_copy, "default_background", None)
            if not candidate and url_name == "home":
                candidate = getattr(page_copy, "hero_background_asset", None)
            if candidate and candidate.is_active and candidate.image:
                page_asset = candidate
        except Exception:
            page_asset = None

    payload = resolve_media_asset(
        location_key,
        defaults["path"],
        defaults.get("alt") or f"BGM — {url_name or 'preview'}",
        defaults.get("caption", DEFAULT_CAPTION),
        asset=page_asset,
    )
    payload["location"] = url_name or payload.get("location", "")

    hero_carousel = []
    if url_name == "home":
        hero_carousel = build_home_hero_carousel()

    return {"hero_media": payload, "hero_carousel": hero_carousel}


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
            "default_keywords": config.get("default_keywords") or "",
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


def topbar_style(request):
    settings_obj = TopbarSettings.get_solo()
    brand_font = settings_obj.brand_font
    brand_word_white_font = settings_obj.brand_word_white_font
    brand_word_red_font = settings_obj.brand_word_red_font
    brand_word_middle_font = settings_obj.brand_word_middle_font
    nav_font = settings_obj.nav_font
    tagline_word_1_font = settings_obj.tagline_word_1_font
    tagline_word_2_font = settings_obj.tagline_word_2_font
    tagline_word_3_font = settings_obj.tagline_word_3_font

    fonts = []
    for font in (
        brand_font,
        brand_word_white_font,
        brand_word_middle_font,
        brand_word_red_font,
        nav_font,
        tagline_word_1_font,
        tagline_word_2_font,
        tagline_word_3_font,
    ):
        if not font or not font.url:
            continue
        serialized = serialize_font_preset(font)
        if serialized and serialized not in fonts:
            fonts.append(serialized)

    return {
        "topbar_settings": {
            "brand": serialize_font_preset(brand_font),
            "brand_word_1": serialize_font_preset(brand_word_white_font),
            "brand_word_2": serialize_font_preset(brand_word_middle_font),
            "brand_word_3": serialize_font_preset(brand_word_red_font),
            "nav": serialize_font_preset(nav_font),
            "tagline_word_1": serialize_font_preset(tagline_word_1_font),
            "tagline_word_2": serialize_font_preset(tagline_word_2_font),
            "tagline_word_3": serialize_font_preset(tagline_word_3_font),
            "brand_size": settings_obj.brand_size_desktop,
            "brand_weight": settings_obj.brand_weight,
            "brand_letter_spacing": settings_obj.brand_letter_spacing,
            "brand_transform": settings_obj.brand_transform,
            "nav_size": settings_obj.nav_size,
            "nav_size_desktop": settings_obj.nav_size_desktop,
            "padding_y_desktop": settings_obj.padding_y_desktop,
            "order_brand": settings_obj.order_brand,
            "order_tagline": settings_obj.order_tagline,
            "order_nav": settings_obj.order_nav,
            "brand_word_1_color": settings_obj.brand_word_1_color,
            "brand_word_2_color": settings_obj.brand_word_2_color,
            "brand_word_3_color": settings_obj.brand_word_3_color,
            "brand_word_1_size": settings_obj.brand_word_1_size,
            "brand_word_2_size": settings_obj.brand_word_2_size,
            "brand_word_3_size": settings_obj.brand_word_3_size,
            "brand_word_1_weight": settings_obj.brand_word_1_weight,
            "brand_word_2_weight": settings_obj.brand_word_2_weight,
            "brand_word_3_weight": settings_obj.brand_word_3_weight,
            "brand_word_1_style": settings_obj.brand_word_1_style,
            "brand_word_2_style": settings_obj.brand_word_2_style,
            "brand_word_3_style": settings_obj.brand_word_3_style,
            "tagline_word_1_color": settings_obj.tagline_word_1_color,
            "tagline_word_2_color": settings_obj.tagline_word_2_color,
            "tagline_word_3_color": settings_obj.tagline_word_3_color,
            "tagline_word_1_size": settings_obj.tagline_word_1_size,
            "tagline_word_2_size": settings_obj.tagline_word_2_size,
            "tagline_word_3_size": settings_obj.tagline_word_3_size,
            "tagline_word_1_weight": settings_obj.tagline_word_1_weight,
            "tagline_word_2_weight": settings_obj.tagline_word_2_weight,
            "tagline_word_3_weight": settings_obj.tagline_word_3_weight,
            "tagline_word_1_style": settings_obj.tagline_word_1_style,
            "tagline_word_2_style": settings_obj.tagline_word_2_style,
            "tagline_word_3_style": settings_obj.tagline_word_3_style,
            "fonts": fonts,
        }
    }


def cart_summary(request):
    """
    Expose a lightweight cart count for global UI elements (e.g., floating cart button).
    """
    cart_item_count = 0
    cart_line_count = 0

    if request is None:
        return {
            "cart_item_count": cart_item_count,
            "cart_line_count": cart_line_count,
        }

    session = getattr(request, "session", None)
    if session is None:
        return {
            "cart_item_count": cart_item_count,
            "cart_line_count": cart_line_count,
        }

    data = session.get("cart_items")
    if not data:
        return {
            "cart_item_count": cart_item_count,
            "cart_line_count": cart_line_count,
        }

    items = []
    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            items = data.get("items") or []
        else:
            for qty in data.values():
                try:
                    qty_value = max(1, int(qty))
                except (TypeError, ValueError):
                    continue
                cart_item_count += qty_value
                cart_line_count += 1
            return {
                "cart_item_count": cart_item_count,
                "cart_line_count": cart_line_count,
            }
    elif isinstance(data, list):
        items = data

    for entry in items:
        if isinstance(entry, dict):
            raw_qty = entry.get("qty", 1)
        else:
            raw_qty = entry
        try:
            qty_value = max(1, int(raw_qty))
        except (TypeError, ValueError):
            continue
        cart_item_count += qty_value
        cart_line_count += 1

    return {
        "cart_item_count": cart_item_count,
        "cart_line_count": cart_line_count,
    }
