from __future__ import annotations

from typing import Iterable, Dict, Any

from django.utils.text import capfirst

from core.email_templates import EMAIL_TEMPLATE_DEFINITIONS
from core.models import EmailCampaign, EmailTemplate


_SPECIAL_TYPES: dict[str, dict[str, str]] = {
    "email_verification": {
        "label": "Email verification",
        "description": "Sent to confirm new account email addresses.",
        "category": "System",
    },
    "generic": {
        "label": "Generic email",
        "description": "Fallback for sends without a template slug.",
        "category": "System",
    },
}


def _titleize(value: str) -> str:
    if not value:
        return ""
    cleaned = value.replace("-", " ").replace("_", " ").strip()
    if not cleaned:
        return ""
    return " ".join(capfirst(part) for part in cleaned.split())


def describe_email_types(email_types: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    types = [t for t in email_types if t]
    if not types:
        return {}

    unique_types = sorted(set(types))
    template_records = {
        row["slug"]: row
        for row in EmailTemplate.objects.filter(slug__in=unique_types).values(
            "slug",
            "name",
            "description",
        )
    }

    campaign_ids = []
    for email_type in unique_types:
        if not email_type.startswith("campaign:"):
            continue
        token = email_type.split(":", 1)[1]
        try:
            campaign_ids.append(int(token))
        except (TypeError, ValueError):
            continue

    campaigns = {
        campaign.id: campaign
        for campaign in EmailCampaign.objects.filter(id__in=campaign_ids).only(
            "id",
            "name",
            "subject",
        )
    }

    results: Dict[str, Dict[str, Any]] = {}
    for email_type in unique_types:
        info: Dict[str, Any] = {
            "slug": email_type,
            "label": _titleize(email_type) or email_type,
            "description": "",
            "category": "Other",
        }

        if email_type in _SPECIAL_TYPES:
            info.update(_SPECIAL_TYPES[email_type])
        elif email_type.startswith("campaign:"):
            info["category"] = "Campaign"
            token = email_type.split(":", 1)[1]
            campaign = None
            try:
                campaign = campaigns.get(int(token))
            except (TypeError, ValueError):
                campaign = None
            if campaign:
                info["label"] = f"Campaign: {campaign.name}"
                info["description"] = campaign.subject or "Marketing campaign broadcast."
                info["campaign_id"] = campaign.id
                info["campaign_name"] = campaign.name
            else:
                info["label"] = "Campaign (missing)"
                info["description"] = "Campaign record not found."
        elif email_type.startswith("staff_"):
            info["category"] = "Staff"
            event_label = _titleize(email_type.replace("staff_", ""))
            info["label"] = f"Staff alert: {event_label}" if event_label else "Staff alert"
            info["description"] = "Internal staff notification."
        elif email_type in template_records:
            record = template_records[email_type]
            info["category"] = "Automated"
            info["label"] = record.get("name") or info["label"]
            info["description"] = record.get("description") or ""
        elif email_type in EMAIL_TEMPLATE_DEFINITIONS:
            definition = EMAIL_TEMPLATE_DEFINITIONS[email_type]
            info["category"] = "Automated"
            info["label"] = definition.name
            info["description"] = definition.description

        info["category_class"] = (info.get("category") or "other").lower().replace(" ", "-")
        results[email_type] = info

    return results
