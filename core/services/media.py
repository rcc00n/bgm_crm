from __future__ import annotations

from typing import Dict

from django.templatetags.static import static

from core.models import HeroImage

DEFAULT_MEDIA_CAPTION = "Product may not appear exactly as shown."


def resolve_media_asset(
    location: str | HeroImage.Location | None,
    fallback_path: str,
    fallback_alt: str,
    fallback_caption: str = DEFAULT_MEDIA_CAPTION,
    asset: HeroImage | None = None,
) -> Dict[str, str | bool]:
    """
    Resolve a hero/marketing asset with a database override and safe fallback.
    Optional prefetched asset can be passed to avoid extra queries.
    Keeps rendering resilient if the upload is missing or storage is misconfigured.
    """
    payload: Dict[str, str | bool] = {
        "src": static(fallback_path),
        "alt": fallback_alt or "",
        "caption": fallback_caption or "",
        "location": str(location or ""),
        "is_custom": False,
        "title": "",
    }

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

    if hero and hero.image:
        try:
            payload.update(
                {
                    "src": hero.image.url,
                    "alt": hero.alt_text or hero.title or payload["alt"],
                    "caption": hero.caption or payload["caption"],
                    "location": hero.location,
                    "is_custom": True,
                    "title": hero.title or "",
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
    asset_map = _prefetch_hero_assets(locations)

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


def _prefetch_hero_assets(locations: list[str | HeroImage.Location]) -> Dict[str, HeroImage]:
    """Fetch active hero assets for the provided locations in a single query."""
    if not locations:
        return {}

    normalized = [str(location) for location in locations if location]
    if not normalized:
        return {}

    try:
        assets = (
            HeroImage.objects.filter(location__in=normalized, is_active=True)
            .exclude(image="")
        )
    except Exception:
        return {}

    return {asset.location: asset for asset in assets if getattr(asset, "image", None)}
