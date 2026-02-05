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
    return {value for value in raw if isinstance(value, str)}
