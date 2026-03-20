from __future__ import annotations

from typing import Iterable

from django.conf import settings
from django.utils.text import slugify


def _sidebar_config() -> list[dict]:
    return (
        getattr(settings, "ADMIN_SIDEBAR_SECTIONS", None)
        or settings.JAZZMIN_SETTINGS.get("custom_sidebar", [])
        or []
    )


def make_notification_group_key(section_label: str, group_label: str) -> str:
    section_slug = slugify(section_label) or "section"
    group_slug = slugify(group_label) or "group"
    return f"{section_slug}__{group_slug}"


def get_notification_group_aliases() -> dict[str, tuple[str, ...]]:
    raw = getattr(settings, "ADMIN_SIDEBAR_GROUP_ALIASES", None) or {}
    if not isinstance(raw, dict):
        return {}
    aliases: dict[str, tuple[str, ...]] = {}
    for old_key, new_value in raw.items():
        if not isinstance(old_key, str) or not old_key:
            continue
        if isinstance(new_value, str):
            values = (new_value,) if new_value else ()
        elif isinstance(new_value, (list, tuple, set)):
            values = tuple(
                value for value in new_value if isinstance(value, str) and value
            )
        else:
            values = ()
        if values:
            aliases[old_key] = values
    return aliases


def _resolve_notification_group_targets(
    key: str,
    aliases: dict[str, tuple[str, ...]] | None = None,
    seen: set[str] | None = None,
) -> set[str]:
    if not isinstance(key, str) or not key:
        return set()
    aliases = aliases or get_notification_group_aliases()
    seen = seen or set()
    if key in seen:
        return {key}
    targets = aliases.get(key)
    if not targets:
        return {key}
    seen.add(key)
    resolved: set[str] = set()
    for target in targets:
        resolved |= _resolve_notification_group_targets(target, aliases=aliases, seen=set(seen))
    return resolved or {key}


def resolve_notification_group_key(key: str) -> str:
    if not isinstance(key, str) or not key:
        return key
    resolved = sorted(_resolve_notification_group_targets(key))
    return resolved[0] if resolved else key


def resolve_notification_group_keys(keys: Iterable[str]) -> set[str]:
    resolved: set[str] = set()
    aliases = get_notification_group_aliases()
    for key in keys:
        if isinstance(key, str) and key:
            resolved |= _resolve_notification_group_targets(key, aliases=aliases)
    return resolved


def expand_notification_group_keys(keys: Iterable[str]) -> set[str]:
    expanded: set[str] = set()
    aliases = get_notification_group_aliases()
    for key in keys:
        if not isinstance(key, str) or not key:
            continue
        expanded.add(key)
        expanded |= _resolve_notification_group_targets(key, aliases=aliases)
    return expanded


def iter_notification_groups() -> Iterable[dict[str, str]]:
    for section in _sidebar_config():
        section_label = section.get("label", "") or ""
        for group in section.get("groups", []):
            group_label = group.get("label", "") or ""
            key = make_notification_group_key(section_label, group_label)
            label = f"{section_label} / {group_label}" if section_label else group_label
            yield {
                "key": key,
                "section_label": section_label,
                "group_label": group_label,
                "label": label,
            }


def get_notification_group_choices() -> list[tuple[str, str]]:
    return [(group["key"], group["label"]) for group in iter_notification_groups()]


def get_notification_group_keys() -> list[str]:
    return [group["key"] for group in iter_notification_groups()]


def get_disabled_notification_sections(user) -> set[str]:
    profile = getattr(user, "userprofile", None)
    if not profile:
        return set()
    raw = getattr(profile, "admin_notification_disabled_sections", None) or []
    if isinstance(raw, str):
        raw = [raw]
    return expand_notification_group_keys(value for value in raw if isinstance(value, str))
