from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .types import CuratedCategoryImage, SourceProduct

logger = logging.getLogger(__name__)

FASSRIDE_PAGE_BASE_URL = "https://www.fassride.com"
FASSRIDE_API_BASE_URL = "https://shop.fassride.com"
DEFAULT_TIMEOUT = 20.0
CURATED_CATEGORY_COVERS: dict[str, CuratedCategoryImage] = {
    "fass-fuel-systems": CuratedCategoryImage(
        category_slug="fass-fuel-systems",
        source_page_url="https://www.fassride.com/fuel-air-separation-system",
        image_url=(
            "https://lirp.cdn-website.com/d0fc1429/dms3rep/multi/opt/"
            "FASS_FuelAirSeparartionSystems_Universal-705x705-1-1920w.png"
        ),
        label="Fuel-Air Separation System / Universal",
    ),
    "fass-industrial-series": CuratedCategoryImage(
        category_slug="fass-industrial-series",
        source_page_url="https://www.fassride.com/fass-industrial-series-systems-for-detroit-paccar-cat-and-more",
        image_url="https://lirp.cdn-website.com/d0fc1429/dms3rep/multi/opt/FASSIndustrialSeries-1920w.webp",
        label="Industrial Series Hero",
    ),
    "fass-mounting-packages": CuratedCategoryImage(
        category_slug="fass-mounting-packages",
        source_page_url="https://www.fassride.com/how-to-install-the-fass-single-bolt-sump-kit-sk5501",
        image_url=(
            "https://lirp.cdn-website.com/d0fc1429/dms3rep/multi/opt/"
            "How+to+install+the+FASS+Single-Bolt+Sump+Kit+%28SK5501%29-56009f76-1920w.png"
        ),
        label="Mounting Package / Sump Kit",
    ),
    "fass-replacement-parts": CuratedCategoryImage(
        category_slug="fass-replacement-parts",
        source_page_url="https://www.fassride.com/can-i-purchase-individual-fass-diesel-fuel-system-components",
        image_url=(
            "https://lirp.cdn-website.com/d0fc1429/dms3rep/multi/opt/"
            "Can+I+Purchase+Individual+FASS+Diesel+Fuel+System+Components+%282%29-1920w.png"
        ),
        label="Replacement Parts / Components",
    ),
}


class FassrideApiClient:
    def __init__(
        self,
        *,
        api_base_url: str = FASSRIDE_API_BASE_URL,
        page_base_url: str = FASSRIDE_PAGE_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = 3,
        retry_backoff: float = 1.0,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.page_base_url = page_base_url.rstrip("/")
        self.timeout = max(float(timeout), 1.0)
        self.retries = max(int(retries), 1)
        self.retry_backoff = max(float(retry_backoff), 0.0)

    def fetch_catalog(self, *, page_size: int = 1000, sort: str = "CustomAsc") -> list[SourceProduct]:
        payload = self._get_json(
            "/Products/Search",
            {
                "pageSize": max(int(page_size), 1),
                "sort": sort,
            },
        )
        products = payload.get("products") or []
        extracted = [self._extract_source_product(item) for item in products]
        logger.info("Fetched %s FASS source products from API.", len(extracted))
        return extracted

    def fetch_curated_category_covers(
        self,
        *,
        category_slugs: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, CuratedCategoryImage]:
        if not category_slugs:
            return dict(CURATED_CATEGORY_COVERS)
        requested = {slug.strip() for slug in category_slugs if slug and slug.strip()}
        return {
            slug: asset
            for slug, asset in CURATED_CATEGORY_COVERS.items()
            if slug in requested
        }

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = urlencode({key: value for key, value in (params or {}).items() if value not in (None, "")}, doseq=True)
        url = f"{self.api_base_url}{path}"
        if query:
            url = f"{url}?{query}"
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            req = Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "BGM-CRM/1.0",
                },
            )
            try:
                with urlopen(req, timeout=self.timeout) as response:
                    return json.load(response)
            except Exception as exc:  # pragma: no cover - exercised in command/runtime
                last_error = exc
                if attempt >= self.retries:
                    break
                sleep_for = self.retry_backoff * attempt
                logger.warning("FASS API request failed (%s/%s): %s", attempt, self.retries, exc)
                if sleep_for > 0:
                    time.sleep(sleep_for)
        assert last_error is not None
        raise last_error

    def _extract_source_product(self, payload: dict[str, Any]) -> SourceProduct:
        product_id = int(payload.get("id") or 0)
        options = tuple(
            str(item.get("name") or "").strip()
            for item in (payload.get("options") or [])
            if str(item.get("name") or "").strip()
        )
        variations = tuple(
            str(item.get("value") or item.get("name") or "").strip()
            for item in (payload.get("variations") or [])
            if str(item.get("value") or item.get("name") or "").strip()
        )
        image_urls: list[str] = []
        seen = set()
        for raw_url in payload.get("images") or []:
            url = str(raw_url or "").strip()
            if not url or url in seen:
                continue
            image_urls.append(url)
            seen.add(url)
        return SourceProduct(
            product_id=product_id,
            part_number=str(payload.get("partNumber") or "").strip(),
            supplier_name=str(payload.get("supplierName") or "").strip(),
            supplier_category=str(payload.get("supplierCategory") or "").strip(),
            name=str(payload.get("shortDescription") or "").strip(),
            medium_description=str(payload.get("mediumDescription") or "").strip(),
            long_description=str(payload.get("longDescription") or "").strip(),
            product_page_url=f"{self.page_base_url}/details?id={product_id}",
            image_urls=tuple(image_urls),
            option_names=options,
            variation_names=variations,
        )
