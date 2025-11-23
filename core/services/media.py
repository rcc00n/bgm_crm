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
