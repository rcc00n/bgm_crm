from __future__ import annotations

import json
from typing import Any, Dict, Mapping

from core.models import HomePageCopy

HOME_LAYOUT_CONFIG: Dict[str, Dict[str, str]] = {
    "hero_logo": {"selector": ".hero__logo-block", "label": "Hero logo"},
    "hero_kicker": {"selector": ".hero .kicker", "label": "Hero kicker"},
    "hero_title": {"selector": ".hero__title", "label": "Hero title"},
    "hero_lead": {"selector": ".hero__lead", "label": "Hero lead"},
    "hero_cta": {"selector": ".hero__cta", "label": "Hero buttons"},
    "hero_stats": {"selector": ".hero__stats", "label": "Hero stats"},
    "hero_media": {"selector": ".hero__media", "label": "Hero media"},
    "hero_quick_actions": {"selector": ".mobi-quick", "label": "Hero quick actions"},
}

PAGE_LAYOUT_CONFIG: Dict[type, Dict[str, Dict[str, str]]] = {
    HomePageCopy: HOME_LAYOUT_CONFIG,
}


def layout_config_for_model(model_cls: type) -> Dict[str, Dict[str, str]]:
    return PAGE_LAYOUT_CONFIG.get(model_cls, {})


def _parse_json(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def normalize_layout_overrides(value: Any) -> Dict[str, Dict[str, Dict[str, int]]]:
    raw = _parse_json(value)
    if not raw:
        return {"desktop": {}, "mobile": {}}
    if "desktop" in raw or "mobile" in raw:
        return {
            "desktop": _parse_json(raw.get("desktop")) or {},
            "mobile": _parse_json(raw.get("mobile")) or {},
        }
    return {"desktop": raw, "mobile": {}}


def _coerce_offset(value: Any) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return 0


def _build_mode_styles(config: Mapping[str, Mapping[str, str]], overrides: Mapping[str, Any]) -> str:
    lines = []
    for key, meta in config.items():
        selector = meta.get("selector") if isinstance(meta, dict) else None
        if not selector:
            continue
        raw = overrides.get(key)
        if not isinstance(raw, dict):
            continue
        x = _coerce_offset(raw.get("x", 0))
        y = _coerce_offset(raw.get("y", 0))
        if not x and not y:
            continue
        lines.append(f"{selector}{{transform:translate3d({x}px,{y}px,0);}}")
    return "\n".join(lines)


def build_layout_styles(model_cls: type, overrides: Any) -> str:
    config = layout_config_for_model(model_cls)
    if not config:
        return ""
    normalized = normalize_layout_overrides(overrides)
    desktop_css = _build_mode_styles(config, normalized.get("desktop", {}))
    mobile_css = _build_mode_styles(config, normalized.get("mobile", {}))
    if not desktop_css and not mobile_css:
        return ""
    if desktop_css and mobile_css:
        return f"{desktop_css}\n@media (max-width: 768px){{{mobile_css}}}"
    if mobile_css:
        return f"@media (max-width: 768px){{{mobile_css}}}"
    return desktop_css
