from __future__ import annotations

from typing import Mapping


_UNKNOWN_CF_CODES = {"", "XX"}


def _clean(value: str | None) -> str:
    if not value:
        return ""
    cleaned = str(value).strip()
    if not cleaned or cleaned.upper() in _UNKNOWN_CF_CODES:
        return ""
    return cleaned


def get_client_ip(meta: Mapping[str, str]) -> str | None:
    """
    Resolve the best-effort client IP using common proxy headers.
    """
    cf_ip = meta.get("HTTP_CF_CONNECTING_IP")
    if cf_ip:
        return cf_ip.strip()
    forwarded = meta.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        return first or None
    remote = meta.get("REMOTE_ADDR")
    return remote.strip() if remote else None


def format_ip_location(meta: Mapping[str, str]) -> str:
    """
    Build a compact location string from Cloudflare geolocation headers.
    """
    city = _clean(meta.get("HTTP_CF_IPCITY"))
    region = _clean(meta.get("HTTP_CF_IPREGION"))
    country = _clean(meta.get("HTTP_CF_IPCOUNTRY"))

    parts = []
    for part in (city, region, country):
        if part and part not in parts:
            parts.append(part)
    return ", ".join(parts)
