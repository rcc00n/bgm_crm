"""Preserve valid customer inquiries before applying content review routing."""
from django.db import transaction

from .lead_security import assess_lead_content
from .lead_review import register_lead_review


def save_public_lead(form, evaluation, entity_type):
    lead = form.save(commit=False)
    text = "\n".join(str(getattr(lead, name, "") or "") for name in ("notes", "frustration", "service_needed"))
    assessment = assess_lead_content(text=text, email=lead.email, phone=lead.phone)
    if assessment.requires_review:
        evaluation.action = "suspect"
        evaluation.reasons = list(dict.fromkeys(evaluation.reasons + assessment.reasons))
    with transaction.atomic():
        lead.save()
        case = (
            register_lead_review(entity_type, lead.pk, assessment, evaluation)
            if evaluation.action == "suspect" else None
        )
    return lead, assessment, case
