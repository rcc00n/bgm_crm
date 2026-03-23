from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from django.core.files.storage import default_storage

from .types import SourceProduct

logger = logging.getLogger(__name__)

DIRTYDIESEL_BASE_URL = "https://www.dirtydieselcustom.ca"
DEFAULT_TIMEOUT = 20.0
IGNORED_IMAGE_TERMS = ("banner", "favicon", "icon", "logo", "placeholder", "social")


class DirtyDieselCatalogClient:
    def __init__(
        self,
        *,
        base_url: str = DIRTYDIESEL_BASE_URL,
        catalog_label: str = "Dirty Diesel",
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = 5,
        retry_backoff: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.catalog_label = str(catalog_label or "Supplier").strip()
        self.timeout = max(float(timeout), 1.0)
        self.retries = max(int(retries), 1)
        self.retry_backoff = max(float(retry_backoff), 0.0)

    def fetch_catalog(
        self,
        *,
        page_size: int = 250,
        max_pages: int | None = None,
        page_delay: float = 0.25,
    ) -> list[SourceProduct]:
        extracted: list[SourceProduct] = []
        page = 1
        while True:
            if max_pages is not None and page > max(int(max_pages), 0):
                break
            payload = self._get_json(f"/products.json?limit={max(int(page_size), 1)}&page={page}")
            products = payload.get("products") or []
            if not products:
                break
            for item in products:
                extracted.extend(self._extract_source_products(item))
            logger.info(
                "Fetched %s %s source variants after page %s.",
                len(extracted),
                self.catalog_label,
                page,
            )
            page += 1
            if page_delay > 0:
                time.sleep(page_delay)
        logger.info("Fetched %s %s source variants total.", len(extracted), self.catalog_label)
        return extracted

    def _get_json(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
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
            except HTTPError as exc:  # pragma: no cover - exercised in command/runtime
                last_error = exc
                if attempt >= self.retries:
                    break
                retry_after = self._retry_after_seconds(exc)
                sleep_for = max(retry_after, self.retry_backoff * (2 ** (attempt - 1)) * 5.0, 5.0)
                logger.warning(
                    "%s catalog request rate-limited (%s/%s): %s; sleeping %.1fs",
                    self.catalog_label,
                    attempt,
                    self.retries,
                    exc,
                    sleep_for,
                )
                time.sleep(sleep_for)
            except Exception as exc:  # pragma: no cover - exercised in command/runtime
                last_error = exc
                if attempt >= self.retries:
                    break
                sleep_for = self.retry_backoff * (2 ** (attempt - 1))
                logger.warning(
                    "%s catalog request failed (%s/%s): %s",
                    self.catalog_label,
                    attempt,
                    self.retries,
                    exc,
                )
                if sleep_for > 0:
                    time.sleep(sleep_for)
        assert last_error is not None
        raise last_error

    def _retry_after_seconds(self, exc: HTTPError) -> float:
        raw = str(exc.headers.get("Retry-After") or "").strip()
        if not raw:
            return 0.0
        try:
            return max(float(raw), 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _extract_source_products(self, payload: dict[str, Any]) -> list[SourceProduct]:
        product_id = int(payload.get("id") or 0)
        handle = str(payload.get("handle") or "").strip()
        product_name = str(payload.get("title") or "").strip()
        supplier_name = str(payload.get("vendor") or "").strip()
        supplier_category = str(payload.get("product_type") or "").strip()
        product_page_url = f"{self.base_url}/products/{handle}" if handle else self.base_url
        raw_tags = payload.get("tags") or []
        if isinstance(raw_tags, str):
            tag_values = [item.strip() for item in raw_tags.split(",")]
        else:
            tag_values = [str(item or "").strip() for item in raw_tags]
        tags = tuple(item for item in tag_values if item)
        images = list(payload.get("images") or [])
        variants = list(payload.get("variants") or [])

        extracted: list[SourceProduct] = []
        for variant in variants:
            sku = str(variant.get("sku") or "").strip()
            if not sku:
                continue
            variant_id = int(variant.get("id") or 0)
            variant_name = str(variant.get("title") or "").strip()
            image_urls = tuple(self._extract_variant_image_urls(images, variant_id))
            extracted.append(
                SourceProduct(
                    product_id=product_id,
                    variant_id=variant_id,
                    sku=sku,
                    product_name=product_name,
                    variant_name=variant_name,
                    supplier_name=supplier_name,
                    supplier_category=supplier_category,
                    product_page_url=product_page_url,
                    image_urls=image_urls,
                    tags=tags,
                )
            )
        return extracted

    def _extract_variant_image_urls(self, images: list[dict[str, Any]], variant_id: int) -> list[str]:
        scoped: list[str] = []
        product_wide: list[str] = []
        other_variant: list[str] = []
        seen = set()

        ordered = sorted(
            images,
            key=lambda item: (int(item.get("position") or 0), int(item.get("id") or 0)),
        )
        for image in ordered:
            raw_url = str(image.get("src") or "").strip()
            url = self._normalize_image_url(raw_url)
            if not url or url in seen or not self._is_usable_image_candidate(url):
                continue
            seen.add(url)
            variant_ids = [int(item or 0) for item in (image.get("variant_ids") or []) if int(item or 0)]
            if variant_ids and variant_id in variant_ids:
                scoped.append(url)
            elif not variant_ids:
                product_wide.append(url)
            else:
                other_variant.append(url)
        return scoped + product_wide + other_variant

    def _normalize_image_url(self, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if value.startswith("//"):
            return f"https:{value}"
        if value.startswith("/"):
            return f"{self.base_url}{value}"
        return value

    def _is_usable_image_candidate(self, url: str) -> bool:
        lower = os.path.basename(url).lower()
        return not any(term in lower for term in IGNORED_IMAGE_TERMS)


def load_source_products(path: str) -> list[SourceProduct]:
    with default_storage.open(path) as fh:
        payload = json.load(fh)
    products = payload.get("products") or []
    extracted: list[SourceProduct] = []
    for item in products:
        extracted.append(
            SourceProduct(
                product_id=int(item.get("product_id") or 0),
                variant_id=int(item.get("variant_id") or 0),
                sku=str(item.get("sku") or "").strip(),
                product_name=str(item.get("product_name") or "").strip(),
                variant_name=str(item.get("variant_name") or "").strip(),
                supplier_name=str(item.get("supplier_name") or "").strip(),
                supplier_category=str(item.get("supplier_category") or "").strip(),
                product_page_url=str(item.get("product_page_url") or "").strip(),
                image_urls=tuple(str(url or "").strip() for url in (item.get("image_urls") or []) if str(url or "").strip()),
                tags=tuple(str(tag or "").strip() for tag in (item.get("tags") or []) if str(tag or "").strip()),
            )
        )
    return extracted
