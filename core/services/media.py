from __future__ import annotations

import logging
from collections import OrderedDict
from functools import lru_cache
from typing import Any, Dict

from django.conf import settings
from django.templatetags.static import static

from core.models import HeroImage, MerchGalleryItem, MerchPageCopy

DEFAULT_MEDIA_CAPTION = "Product may not appear exactly as shown."

logger = logging.getLogger(__name__)

FALLBACK_RESPONSIVE_IMAGES = {
    "img/hero-home.jpg": {
        "width": 987,
        "height": 581,
        "avif": (
            ("img/hero-home-640.avif", 640),
            ("img/hero-home-987.avif", 987),
        ),
        "webp": (
            ("img/hero-home-640.webp", 640),
            ("img/hero-home-987.webp", 987),
        ),
        "jpg": (("img/hero-home.jpg", 987),),
    },
    "img/hero-services.jpg": {
        "width": 1280,
        "height": 1280,
        "avif": (
            ("img/hero-services-420.avif", 420),
            ("img/hero-services-840.avif", 840),
        ),
        "webp": (
            ("img/hero-services-420.webp", 420),
            ("img/hero-services-840.webp", 840),
        ),
        "jpg": (("img/hero-services.jpg", 1280),),
    },
    "img/hero-products.jpg": {
        "width": 960,
        "height": 1280,
        "avif": (
            ("img/hero-products-420.avif", 420),
            ("img/hero-products-840.avif", 840),
        ),
        "webp": (
            ("img/hero-products-420.webp", 420),
            ("img/hero-products-840.webp", 840),
        ),
        "jpg": (("img/hero-products.jpg", 960),),
    },
}


@lru_cache(maxsize=64)
def _safe_static(path: str) -> str:
    """Best-effort static URL resolution for runtime fallbacks.

    With a manifest storage backend (e.g. WhiteNoise), missing manifest entries
    raise ValueError and can take down unrelated pages (admin, product pages)
    because context processors run for every template render.
    """
    try:
        return static(path)
    except Exception as exc:
        # Log once per path (thanks to lru_cache) to avoid spamming logs.
        logger.warning("Static asset missing from manifest: %s (%s)", path, exc)
        static_url = getattr(settings, "STATIC_URL", "/static/")
        return f"{static_url.rstrip('/')}/{path.lstrip('/')}"


def _build_srcset(entries: tuple[tuple[str, int], ...]) -> str:
    if not entries:
        return ""
    return ", ".join(f"{_safe_static(path)} {width}w" for path, width in entries)


def _fallback_responsive_payload(fallback_path: str) -> Dict[str, Any]:
    spec = FALLBACK_RESPONSIVE_IMAGES.get(fallback_path)
    if not spec:
        return {}
    return {
        "fallback_width": spec.get("width"),
        "fallback_height": spec.get("height"),
        "fallback_srcset_avif": _build_srcset(tuple(spec.get("avif", ()))),
        "fallback_srcset_webp": _build_srcset(tuple(spec.get("webp", ()))),
        "fallback_srcset_jpg": _build_srcset(tuple(spec.get("jpg", ()))),
    }


def resolve_media_asset(
    location: str | HeroImage.Location | None,
    fallback_path: str,
    fallback_alt: str,
    fallback_caption: str = DEFAULT_MEDIA_CAPTION,
    asset: HeroImage | None = None,
) -> Dict[str, Any]:
    """
    Resolve a hero/marketing asset with a database override and safe fallback.
    Optional prefetched asset can be passed to avoid extra queries.
    Keeps rendering resilient if the upload is missing or storage is misconfigured.
    """
    payload: Dict[str, Any] = {
        "src": _safe_static(fallback_path),
        "alt": fallback_alt or "",
        "caption": fallback_caption or "",
        "location": str(location or ""),
        "is_custom": False,
        "title": "",
        "image": None,  # ImageFieldFile when the source is a DB upload.
    }
    payload.update(_fallback_responsive_payload(fallback_path))

    hero = asset
    if hero is None and not location:
        return payload

    if hero is None:
        try:
            hero = (
                HeroImage.objects.filter(location=location, is_active=True)
                .exclude(image="")
                .first()
            )
        except Exception:
            hero = None

    if hero:
        hero_alt = getattr(hero, "alt_text", "") or getattr(hero, "title", "")
        hero_caption = getattr(hero, "caption", "")
        hero_title = getattr(hero, "title", "")
        payload.update(
            {
                "alt": hero_alt or payload["alt"],
                "caption": hero_caption or payload["caption"],
                "location": getattr(hero, "location", payload["location"]),
                "title": hero_title or payload.get("title", ""),
            }
        )
        if hero.image:
            try:
                payload.update(
                    {
                        "src": hero.image.url,
                        "is_custom": True,
                        "image": hero.image,
                    }
                )
            except Exception:
                # Keep fallbacks intact if storage fails or the URL can't be resolved.
                pass

    return payload


def build_home_hero_carousel():
    """
    Carousel assets for the home page hero.
    Returns only active uploaded slides (no fallbacks).
    """
    locations = [
        HeroImage.Location.HOME_CAROUSEL_A,
        HeroImage.Location.HOME_CAROUSEL_B,
        HeroImage.Location.HOME_CAROUSEL_C,
        HeroImage.Location.HOME_CAROUSEL_D,
    ]
    asset_map = _prefetch_hero_assets(locations)

    slides = []
    for location in locations:
        asset = asset_map.get(location)
        if not asset:
            continue
        slide = resolve_media_asset(
            location,
            "img/hero-home.jpg",
            "Home hero",
            DEFAULT_MEDIA_CAPTION,
            asset=asset,
        )
        slide["slot"] = str(location)
        slides.append(slide)

    return slides


def build_home_gallery_media():
    """
    Assets for the home page gallery slots.
    Returns gallery slots with fallbacks to current static imagery.
    """
    locations = [
        HeroImage.Location.HOME_GALLERY_A,
        HeroImage.Location.HOME_GALLERY_B,
        HeroImage.Location.HOME_GALLERY_C,
        HeroImage.Location.HOME_GALLERY_D,
    ]
    asset_map = _prefetch_hero_assets(locations, active_only=False)

    gallery = [
        resolve_media_asset(
            HeroImage.Location.HOME_GALLERY_A,
            "img/hero-home.jpg",
            "Custom fabrication build at Bad Guy Motors",
            "Custom fabrication highlights from recent builds.",
            asset=asset_map.get(HeroImage.Location.HOME_GALLERY_A),
        ),
        resolve_media_asset(
            HeroImage.Location.HOME_GALLERY_B,
            "img/hero-services.jpg",
            "Detailing and coating work in the BGM shop",
            "Detailing, coatings, and finishing touches.",
            asset=asset_map.get(HeroImage.Location.HOME_GALLERY_B),
        ),
        resolve_media_asset(
            HeroImage.Location.HOME_GALLERY_C,
            "img/hero-products.jpg",
            "Performance upgrade install at Bad Guy Motors",
            "Performance installs and hard-part upgrades.",
            asset=asset_map.get(HeroImage.Location.HOME_GALLERY_C),
        ),
        resolve_media_asset(
            HeroImage.Location.HOME_GALLERY_D,
            "img/hero-about.jpg",
            "Custom build progress in the BGM bay",
            "In-progress builds and finished customer rigs.",
            asset=asset_map.get(HeroImage.Location.HOME_GALLERY_D),
        ),
    ]

    for idx, asset in enumerate(gallery, start=1):
        asset["slot"] = f"gallery-{idx}"

    return gallery


def build_merch_gallery_groups(merch_page: MerchPageCopy | None = None) -> list[Dict[str, Any]]:
    """
    Group active merch gallery cards by category while preserving card order.
    """
    page = merch_page
    if page is None:
        try:
            page = MerchPageCopy.get_solo()
        except Exception:
            return []

    page_id = getattr(page, "pk", None)
    if not page_id:
        return []

    try:
        items = list(
            MerchGalleryItem.objects.filter(merch_page_id=page_id, is_active=True)
            .exclude(photo="")
            .order_by("sort_order", "id")
        )
    except Exception:
        return []

    grouped: OrderedDict[str, list[MerchGalleryItem]] = OrderedDict()
    for item in items:
        category = (item.category or "Featured").strip() or "Featured"
        grouped.setdefault(category, []).append(item)

    return [{"title": title, "items": cards} for title, cards in grouped.items()]


def build_brake_suspension_media():
    """
    Assets for the Brake & Suspension landing page.
    Returns hero + gallery slots with fallbacks to current static imagery.
    """
    locations = [
        HeroImage.Location.BRAKE_SUSPENSION_HERO,
        HeroImage.Location.BRAKE_SUSPENSION_GALLERY_A,
        HeroImage.Location.BRAKE_SUSPENSION_GALLERY_B,
        HeroImage.Location.BRAKE_SUSPENSION_GALLERY_C,
    ]
    asset_map = _prefetch_hero_assets(locations)

    hero = resolve_media_asset(
        HeroImage.Location.BRAKE_SUSPENSION_HERO,
        "img/hero-services.jpg",
        "Brake and suspension work at Bad Guy Motors",
        asset=asset_map.get(HeroImage.Location.BRAKE_SUSPENSION_HERO),
    )
    hero["slot"] = "hero"

    gallery = [
        resolve_media_asset(
            HeroImage.Location.BRAKE_SUSPENSION_GALLERY_A,
            "img/hero-dealers.jpg",
            "Suspension work on a truck at Bad Guy Motors",
            "Heavy-duty suspension service on work trucks.",
            asset=asset_map.get(HeroImage.Location.BRAKE_SUSPENSION_GALLERY_A),
        ),
        resolve_media_asset(
            HeroImage.Location.BRAKE_SUSPENSION_GALLERY_B,
            "img/hero-about.jpg",
            "Lifted truck brake and suspension setup in the shop",
            "Lifted truck brake and suspension setup checked for safety.",
            asset=asset_map.get(HeroImage.Location.BRAKE_SUSPENSION_GALLERY_B),
        ),
        resolve_media_asset(
            HeroImage.Location.BRAKE_SUSPENSION_GALLERY_C,
            "img/hero-home.jpg",
            "Front end and alignment work at Bad Guy Motors",
            "Precision front end and alignment work for a straight drive.",
            asset=asset_map.get(HeroImage.Location.BRAKE_SUSPENSION_GALLERY_C),
        ),
    ]

    for idx, asset in enumerate(gallery, start=1):
        asset["slot"] = f"gallery-{idx}"

    return {"hero": hero, "gallery": gallery}


def build_electrical_work_media():
    """
    Assets for the Electrical Work landing page.
    Returns hero + gallery slots with fallbacks to current static imagery.
    """
    locations = [
        HeroImage.Location.ELECTRICAL_WORK_HERO,
        HeroImage.Location.ELECTRICAL_WORK_GALLERY_A,
        HeroImage.Location.ELECTRICAL_WORK_GALLERY_B,
        HeroImage.Location.ELECTRICAL_WORK_GALLERY_C,
    ]
    asset_map = _prefetch_hero_assets(locations)

    hero = resolve_media_asset(
        HeroImage.Location.ELECTRICAL_WORK_HERO,
        "img/hero-services.jpg",
        "Auto electrical work at Bad Guy Motors",
        "Electrical diagnostics and repair for reliable starts.",
        asset=asset_map.get(HeroImage.Location.ELECTRICAL_WORK_HERO),
    )
    hero["slot"] = "hero"

    gallery = [
        resolve_media_asset(
            HeroImage.Location.ELECTRICAL_WORK_GALLERY_A,
            "img/hero-dealers.jpg",
            "Electrical diagnostics on a truck at Bad Guy Motors",
            "Electrical diagnostics, battery, and charging system checks.",
            asset=asset_map.get(HeroImage.Location.ELECTRICAL_WORK_GALLERY_A),
        ),
        resolve_media_asset(
            HeroImage.Location.ELECTRICAL_WORK_GALLERY_B,
            "img/hero-about.jpg",
            "Battery and wiring repair at Bad Guy Motors",
            "Battery, cable, and wiring repair for dependable starts.",
            asset=asset_map.get(HeroImage.Location.ELECTRICAL_WORK_GALLERY_B),
        ),
        resolve_media_asset(
            HeroImage.Location.ELECTRICAL_WORK_GALLERY_C,
            "img/hero-home.jpg",
            "Lighting and accessory wiring install at Bad Guy Motors",
            "Accessory lighting, power, and wiring installed cleanly.",
            asset=asset_map.get(HeroImage.Location.ELECTRICAL_WORK_GALLERY_C),
        ),
    ]

    for idx, asset in enumerate(gallery, start=1):
        asset["slot"] = f"gallery-{idx}"

    return {"hero": hero, "gallery": gallery}


def build_performance_tuning_media():
    """
    Assets for the Performance Tuning landing page.
    Returns hero + gallery slots with fallbacks to current static imagery.
    """
    locations = [
        HeroImage.Location.PERFORMANCE_TUNING_HERO,
        HeroImage.Location.PERFORMANCE_TUNING_GALLERY_A,
        HeroImage.Location.PERFORMANCE_TUNING_GALLERY_B,
        HeroImage.Location.PERFORMANCE_TUNING_GALLERY_C,
    ]
    asset_map = _prefetch_hero_assets(locations)

    hero = resolve_media_asset(
        HeroImage.Location.PERFORMANCE_TUNING_HERO,
        "img/hero-services.jpg",
        "Performance tuning and engine upgrades at Bad Guy Motors",
        asset=asset_map.get(HeroImage.Location.PERFORMANCE_TUNING_HERO),
    )
    hero["slot"] = "hero"

    gallery = [
        resolve_media_asset(
            HeroImage.Location.PERFORMANCE_TUNING_GALLERY_A,
            "img/hero-home.jpg",
            "Dyno-backed performance tuning at Bad Guy Motors",
            "Dyno-backed performance tuning for reliable power.",
            asset=asset_map.get(HeroImage.Location.PERFORMANCE_TUNING_GALLERY_A),
        ),
        resolve_media_asset(
            HeroImage.Location.PERFORMANCE_TUNING_GALLERY_B,
            "img/hero-about.jpg",
            "Performance upgrades and airflow work in the bay",
            "Performance upgrades, airflow, and supporting hardware installs.",
            asset=asset_map.get(HeroImage.Location.PERFORMANCE_TUNING_GALLERY_B),
        ),
        resolve_media_asset(
            HeroImage.Location.PERFORMANCE_TUNING_GALLERY_C,
            "img/hero-dealers.jpg",
            "Tuning technicians working on a truck",
            "Technicians calibrating and verifying performance setups.",
            asset=asset_map.get(HeroImage.Location.PERFORMANCE_TUNING_GALLERY_C),
        ),
    ]

    for idx, asset in enumerate(gallery, start=1):
        asset["slot"] = f"gallery-{idx}"

    return {"hero": hero, "gallery": gallery}


def _prefetch_hero_assets(
    locations: list[str | HeroImage.Location],
    *,
    active_only: bool = True,
) -> Dict[str, HeroImage]:
    """Fetch hero assets for the provided locations in a single query."""
    if not locations:
        return {}

    normalized = [str(location) for location in locations if location]
    if not normalized:
        return {}

    try:
        assets = HeroImage.objects.filter(location__in=normalized)
        if active_only:
            assets = assets.filter(is_active=True).exclude(image="")
    except Exception:
        return {}

    if active_only:
        return {asset.location: asset for asset in assets if getattr(asset, "image", None)}
    return {asset.location: asset for asset in assets}
