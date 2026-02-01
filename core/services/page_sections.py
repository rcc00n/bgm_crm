from __future__ import annotations

from typing import List

from django.contrib.contenttypes.models import ContentType

from core.models import PageSection


def get_page_sections(instance, include_hidden: bool = False) -> List[PageSection]:
    if not instance or not getattr(instance, "pk", None):
        return []
    content_type = ContentType.objects.get_for_model(instance.__class__)
    qs = PageSection.objects.filter(content_type=content_type, object_id=instance.pk)
    if not include_hidden:
        qs = qs.filter(is_hidden=False)
    return list(qs.order_by("order", "id"))
