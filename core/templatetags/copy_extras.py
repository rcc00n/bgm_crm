from __future__ import annotations

import re
from typing import Any

from django import template

register = template.Library()


# Site-wide placeholder copy that should not render on public pages.
_PLACEHOLDER_DISCLAIMER_NORMALIZED = {
    "product may not appear exactly as shown",
    "product may not be exactly as shown",
    "product may not look exactly as shown",
    # Legacy hero caption label we don't want visible on the homepage carousel.
    "outlaw series",
}

_DISCLAIMER_PHRASE_RE = re.compile(
    r"(?i)\bproduct\s+may\s+not\s+(?:appear|be|look)\s+exactly\s+as\s+shown\b\.?\s*"
)


def _normalize_disclaimer(value: str) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip().lower())
    # Allow minor punctuation differences.
    return text.rstrip(" .!?:;")


@register.filter(name="suppress_placeholder_disclaimer")
def suppress_placeholder_disclaimer(value: Any) -> str:
    """
    Hide boilerplate hero captions/disclaimers that we don't want visible on the site.

    Returns an empty string for known placeholder disclaimers (case/whitespace/punctuation agnostic),
    otherwise returns the original value (stringified).
    """
    if value is None:
        return ""

    text = str(value).strip()
    if not text:
        return ""

    if _normalize_disclaimer(text) in _PLACEHOLDER_DISCLAIMER_NORMALIZED:
        return ""

    # Remove the boilerplate phrase even when it's embedded inside a longer caption,
    # e.g. "OUTLAW SERIES - PRODUCT MAY NOT APPEAR EXACTLY AS SHOWN".
    if _DISCLAIMER_PHRASE_RE.search(text):
        cleaned = _DISCLAIMER_PHRASE_RE.sub("", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"^[\s\-–—|•:]+", "", cleaned).strip()
        cleaned = re.sub(r"[\s\-–—|•:]+$", "", cleaned).strip()
        if not cleaned:
            return ""
        # If removing the boilerplate leaves us with a legacy label we also
        # want hidden (e.g. "Outlaw Series"), suppress it.
        if _normalize_disclaimer(cleaned) in _PLACEHOLDER_DISCLAIMER_NORMALIZED:
            return ""
        return cleaned

    return text
