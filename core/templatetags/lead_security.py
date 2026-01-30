from __future__ import annotations

from django import template
from django.utils import timezone

from core.services.lead_security import HONEYPOT_FIELD, build_form_token, ensure_session_key

register = template.Library()


@register.inclusion_tag("includes/lead_security_fields.html", takes_context=True)
def lead_security_fields(context, purpose: str = "service_lead"):
    request = context.get("request")
    if not request:
        return {"form_token": "", "honeypot_name": HONEYPOT_FIELD}

    session_key = ensure_session_key(request)
    if session_key and "lead_first_seen_at" not in request.session:
        request.session["lead_first_seen_at"] = timezone.now().isoformat()

    token = build_form_token(session_key=session_key, purpose=purpose) if session_key else ""
    return {"form_token": token, "honeypot_name": HONEYPOT_FIELD}
