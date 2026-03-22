from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import time
from dataclasses import dataclass
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils.text import slugify

logger = logging.getLogger(__name__)

IMAGE_CONTENT_TYPE_PREFIX = "image/"
KNOWN_IMAGE_SUFFIXES = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


@dataclass(frozen=True)
class ImageCheck:
    ok: bool
    content_type: str = ""
    error: str = ""


class ImageAssetManager:
    def __init__(
        self,
        *,
        storage_prefix: str = "store/imports/fassride/assets",
        timeout: float = 20.0,
        retries: int = 3,
        retry_backoff: float = 1.0,
    ) -> None:
        self.storage_prefix = storage_prefix.strip().strip("/") or "store/imports/fassride/assets"
        self.timeout = max(float(timeout), 1.0)
        self.retries = max(int(retries), 1)
        self.retry_backoff = max(float(retry_backoff), 0.0)
        self._checks: dict[str, ImageCheck] = {}
        self._localized: dict[str, str] = {}

    def validate(self, url: str) -> ImageCheck:
        url = (url or "").strip()
        if not url:
            return ImageCheck(ok=False, error="empty_url")
        cached = self._checks.get(url)
        if cached is not None:
            return cached
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                req = Request(url, headers={"Accept": "image/*,*/*;q=0.8", "User-Agent": "BGM-CRM/1.0"})
                with urlopen(req, timeout=self.timeout) as response:
                    content_type = str(response.headers.get("Content-Type") or "").strip()
                    response.read(1)
                result = (
                    ImageCheck(ok=True, content_type=content_type)
                    if content_type.startswith(IMAGE_CONTENT_TYPE_PREFIX)
                    else ImageCheck(ok=False, content_type=content_type, error=f"invalid_content_type:{content_type}")
                )
                self._checks[url] = result
                return result
            except Exception as exc:  # pragma: no cover - exercised in command/runtime
                last_error = exc
                if attempt >= self.retries:
                    break
                sleep_for = self.retry_backoff * attempt
                logger.warning("Image validation failed (%s/%s): %s", attempt, self.retries, exc)
                if sleep_for > 0:
                    time.sleep(sleep_for)
        error_name = last_error.__class__.__name__ if last_error else "unknown_error"
        result = ImageCheck(ok=False, error=error_name)
        self._checks[url] = result
        return result

    def localize(self, url: str) -> str:
        url = (url or "").strip()
        if not url:
            raise ValueError("Empty image URL.")
        cached = self._localized.get(url)
        if cached:
            return cached

        check = self.validate(url)
        if not check.ok:
            raise ValueError(f"Image URL is not usable: {url}")

        storage_name = self._storage_name(url, check.content_type)
        if default_storage.exists(storage_name):
            self._localized[url] = storage_name
            return storage_name

        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                req = Request(url, headers={"Accept": "image/*,*/*;q=0.8", "User-Agent": "BGM-CRM/1.0"})
                with urlopen(req, timeout=self.timeout) as response:
                    content_type = str(response.headers.get("Content-Type") or check.content_type).strip()
                    if not content_type.startswith(IMAGE_CONTENT_TYPE_PREFIX):
                        raise ValueError(f"Unexpected content type: {content_type}")
                    body = response.read()
                if not body:
                    raise ValueError("Empty image body.")
                saved_name = default_storage.save(storage_name, ContentFile(body))
                self._localized[url] = saved_name
                self._checks[url] = ImageCheck(ok=True, content_type=content_type)
                return saved_name
            except Exception as exc:  # pragma: no cover - exercised in command/runtime
                last_error = exc
                if attempt >= self.retries:
                    break
                sleep_for = self.retry_backoff * attempt
                logger.warning("Image download failed (%s/%s): %s", attempt, self.retries, exc)
                if sleep_for > 0:
                    time.sleep(sleep_for)
        raise last_error or ValueError(f"Failed to localize image: {url}")

    def storage_name(self, url: str, *, content_type: str = "") -> str:
        url = (url or "").strip()
        if not url:
            raise ValueError("Empty image URL.")
        return self._storage_name(url, content_type)

    def dedupe_urls(self, urls: list[str] | tuple[str, ...]) -> list[str]:
        deduped: list[str] = []
        seen = set()
        for raw_url in urls:
            url = (raw_url or "").strip()
            if not url:
                continue
            key = self._canonical_url(url)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(url)
        return deduped

    def _storage_name(self, url: str, content_type: str) -> str:
        parsed = urlparse(url)
        base_name = os.path.basename(unquote(parsed.path or "")) or "image"
        stem, suffix = os.path.splitext(base_name)
        suffix = (suffix or "").lower()
        if suffix not in KNOWN_IMAGE_SUFFIXES:
            guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip()) or ".jpg"
            suffix = ".jpg" if guessed == ".jpe" else guessed.lower()
        if suffix not in KNOWN_IMAGE_SUFFIXES:
            suffix = ".jpg"
        safe_stem = slugify(stem) or "image"
        digest = hashlib.sha256(self._canonical_url(url).encode("utf-8")).hexdigest()[:16]
        return f"{self.storage_prefix}/{safe_stem}-{digest}{suffix}"

    def _canonical_url(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
