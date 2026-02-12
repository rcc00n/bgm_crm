from __future__ import annotations

from typing import Any


def _coerce_seconds(value: Any) -> int:
    """
    Convert a seconds-like input (float/int/str/Decimal) to an integer seconds count.
    We round to the nearest second to avoid showing milliseconds.
    """
    if value is None:
        return 0
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0
    if seconds <= 0:
        return 0
    return int(round(seconds))


def format_hms_seconds(value: Any) -> str:
    """
    Format a duration as HH:MM:SS (hours can exceed 24).
    """
    total = _coerce_seconds(value)
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_hms_ms(value: Any) -> str:
    """
    Format a millisecond duration as HH:MM:SS.
    """
    if value is None:
        return format_hms_seconds(0)
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return format_hms_seconds(0)
    return format_hms_seconds(ms / 1000.0)

