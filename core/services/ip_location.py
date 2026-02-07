from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from ipaddress import ip_address
from threading import Lock
from typing import Mapping
from urllib.parse import quote
from urllib.request import Request, urlopen


_UNKNOWN_CF_CODES = {"", "XX"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


_CACHE_MAX = max(0, _int_env("IP_GEO_CACHE_MAX", 2048))
_CACHE_TTL_SECONDS = max(0, _int_env("IP_GEO_CACHE_TTL_SECONDS", 60 * 60 * 12))
_CACHE_NEGATIVE_TTL_SECONDS = max(0, _int_env("IP_GEO_CACHE_NEGATIVE_TTL_SECONDS", 600))
_LOOKUP_TIMEOUT_SECONDS = max(0.2, _float_env("IP_GEO_TIMEOUT_SECONDS", 1.0))
_LOOKUP_PROVIDER = os.getenv("IP_GEO_PROVIDER", "ipapi").strip().lower()
_LOOKUP_ENDPOINT = os.getenv("IP_GEO_ENDPOINT", "").strip()

_CACHE: OrderedDict[str, tuple[float, str]] = OrderedDict()
_CACHE_LOCK = Lock()


def _clean(value: str | None) -> str:
    if not value:
        return ""
    cleaned = str(value).strip()
    if not cleaned or cleaned.upper() in _UNKNOWN_CF_CODES:
        return ""
    return cleaned


def _format_location_parts(*parts: str) -> str:
    cleaned = []
    for part in parts:
        if part and part not in cleaned:
            cleaned.append(part)
    return ", ".join(cleaned)


def _is_public_ip(raw_ip: str | None) -> bool:
    if not raw_ip:
        return False
    try:
        parsed = ip_address(raw_ip)
    except ValueError:
        return False
    is_global = getattr(parsed, "is_global", None)
    if is_global is not None:
        return bool(is_global)
    return not (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_reserved
        or parsed.is_multicast
        or parsed.is_unspecified
    )


def _cache_get(ip: str) -> str | None:
    if _CACHE_MAX <= 0:
        return None
    now = time.time()
    with _CACHE_LOCK:
        entry = _CACHE.get(ip)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at <= now:
            _CACHE.pop(ip, None)
            return None
        _CACHE.move_to_end(ip)
        return value


def _cache_set(ip: str, value: str, ttl_seconds: int) -> None:
    if _CACHE_MAX <= 0 or ttl_seconds <= 0:
        return
    expires_at = time.time() + ttl_seconds
    with _CACHE_LOCK:
        _CACHE[ip] = (expires_at, value)
        _CACHE.move_to_end(ip)
        if len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def _build_lookup_url(ip: str) -> str:
    if _LOOKUP_PROVIDER in {"none", "off", "disabled"}:
        return ""
    if _LOOKUP_ENDPOINT:
        try:
            url = _LOOKUP_ENDPOINT.format(ip=ip)
        except Exception:
            url = _LOOKUP_ENDPOINT
        token = (os.getenv("IP_GEO_TOKEN") or "").strip()
        token_param = (os.getenv("IP_GEO_TOKEN_PARAM") or "").strip()
        if token and token_param:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{token_param}={quote(token)}"
        return url

    if _LOOKUP_PROVIDER in {"ipinfo", "ipinfo.io"}:
        url = f"https://ipinfo.io/{ip}/json"
        token = (os.getenv("IPINFO_TOKEN") or os.getenv("IP_GEO_TOKEN") or "").strip()
        if token:
            url = f"{url}?token={quote(token)}"
        return url

    # Default to ipapi.co (free tier is keyless, paid uses ?key=).
    url = f"https://ipapi.co/{ip}/json/"
    token = (os.getenv("IPAPI_KEY") or os.getenv("IP_GEO_TOKEN") or "").strip()
    if token:
        url = f"{url}?key={quote(token)}"
    return url


def _fetch_geo_payload(url: str) -> dict | None:
    if not url:
        return None
    req = Request(url, headers={"User-Agent": "BGM-CRM/1.0"})
    try:
        with urlopen(req, timeout=_LOOKUP_TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", 200)
            if status and int(status) >= 400:
                return None
            payload = resp.read(65536)
    except Exception:
        return None
    try:
        return json.loads(payload.decode("utf-8", errors="ignore"))
    except (TypeError, ValueError):
        return None


def _extract_location(payload: dict | None) -> str:
    if not isinstance(payload, dict) or not payload:
        return ""
    if payload.get("error") or payload.get("bogon"):
        return ""
    status = str(payload.get("status") or "").lower()
    if status == "fail":
        return ""

    city = _clean(payload.get("city"))
    region = _clean(
        payload.get("region")
        or payload.get("region_name")
        or payload.get("regionName")
    )
    country = _clean(
        payload.get("country_name")
        or payload.get("country")
        or payload.get("countryCode")
        or payload.get("country_code")
    )
    return _format_location_parts(city, region, country)


def _format_cf_location(meta: Mapping[str, str]) -> str:
    city = _clean(meta.get("HTTP_CF_IPCITY"))
    region = _clean(meta.get("HTTP_CF_IPREGION"))
    country = _clean(meta.get("HTTP_CF_IPCOUNTRY"))
    return _format_location_parts(city, region, country)


def _lookup_ip_location(ip: str | None) -> str:
    if not _is_public_ip(ip):
        return ""
    cached = _cache_get(ip)
    if cached is not None:
        return cached
    url = _build_lookup_url(ip)
    payload = _fetch_geo_payload(url)
    location = _extract_location(payload)
    ttl = _CACHE_TTL_SECONDS if location else _CACHE_NEGATIVE_TTL_SECONDS
    _cache_set(ip, location, ttl)
    return location


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
    Build a compact location string from geolocation headers or a fallback lookup.
    """
    cf_location = _format_cf_location(meta)
    if cf_location:
        return cf_location
    return _lookup_ip_location(get_client_ip(meta))
