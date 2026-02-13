from __future__ import annotations

from django.db import migrations


def _field_names(model) -> set[str]:
    return {field.name for field in model._meta.get_fields() if getattr(field, "concrete", False)}


def _update_if_contains(model, field: str, needle: str, replacement: str):
    if field not in _field_names(model):
        return
    lookup = {f"{field}__icontains": needle}
    model.objects.filter(**lookup).update(**{field: replacement})


def forwards(apps, schema_editor):
    HomePageCopy = apps.get_model("core", "HomePageCopy")
    ServicesPageCopy = apps.get_model("core", "ServicesPageCopy")
    StorePageCopy = apps.get_model("core", "StorePageCopy")
    ClientPortalPageCopy = apps.get_model("core", "ClientPortalPageCopy")
    MerchPageCopy = apps.get_model("core", "MerchPageCopy")
    FinancingPageCopy = apps.get_model("core", "FinancingPageCopy")
    AboutPageCopy = apps.get_model("core", "AboutPageCopy")
    DealerStatusPageCopy = apps.get_model("core", "DealerStatusPageCopy")
    HomePageFAQItem = apps.get_model("core", "HomePageFAQItem")

    copy_models = [
        HomePageCopy,
        ServicesPageCopy,
        StorePageCopy,
        MerchPageCopy,
        FinancingPageCopy,
        AboutPageCopy,
    ]
    for model in copy_models:
        _update_if_contains(model, "nav_merch_badge", "soon", "")

    _update_if_contains(HomePageCopy, "products_mobile_action_2_subtitle", "soon", "Shop merch")
    _update_if_contains(HomePageCopy, "services_empty_label", "soon", "Catalog is being updated.")
    _update_if_contains(
        HomePageCopy,
        "faq_3_answer",
        "soon",
        "Yes. Dealer applications are open. Leave a request via the contact form.",
    )

    _update_if_contains(ServicesPageCopy, "catalog_empty_label", "soon", "Catalog is being updated.")
    _update_if_contains(ClientPortalPageCopy, "notifications_empty_label", "soon", "No notifications yet.")
    _update_if_contains(DealerStatusPageCopy, "tier_empty_label", "soon", "Tier configuration is being updated.")

    _update_if_contains(MerchPageCopy, "page_title", "soon", "Bad Guy Merch")
    _update_if_contains(MerchPageCopy, "meta_title", "soon", "Bad Guy Merch")
    _update_if_contains(MerchPageCopy, "hero_title", "soon", "Apparel & Accessories")
    _update_if_contains(MerchPageCopy, "coming_soon_badge", "soon", "Update")
    _update_if_contains(MerchPageCopy, "coming_soon_title", "soon", "Merch update")
    _update_if_contains(
        MerchPageCopy,
        "coming_soon_desc",
        "soon",
        "Merch catalog is updated regularly. Check back for fresh drops.",
    )
    if "coming_soon_enabled" in _field_names(MerchPageCopy):
        MerchPageCopy.objects.all().update(coming_soon_enabled=False)

    faq_fields = _field_names(HomePageFAQItem)
    if {"question", "answer"}.issubset(faq_fields):
        for item in HomePageFAQItem.objects.filter(answer__icontains="soon"):
            question = (item.question or "").lower()
            if "dealer" in question:
                item.answer = "Yes. Dealer applications are open. Leave a request via the contact form."
            else:
                item.answer = "Details are available now. Contact us for current options."
            item.save(update_fields=["answer"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0103_projectjournalprocessphoto_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
