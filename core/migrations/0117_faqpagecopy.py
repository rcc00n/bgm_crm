from django.db import migrations, models


def seed_faq_page_copy(apps, schema_editor):
    HomePageCopy = apps.get_model("core", "HomePageCopy")
    FAQPageCopy = apps.get_model("core", "FAQPageCopy")

    home_copy, _ = HomePageCopy.objects.get_or_create(singleton_id=1)
    title = (getattr(home_copy, "faq_title", "") or "").strip() or "FAQ"
    lead = (
        (getattr(home_copy, "faq_desc", "") or "").strip()
        or "Answers to common questions about Bad Guy Motors."
    )

    meta_title = title
    if "bad guy motors" not in title.lower():
        meta_title = f"{title} — Bad Guy Motors"

    FAQPageCopy.objects.update_or_create(
        singleton_id=1,
        defaults={
            "meta_title": meta_title,
            "meta_description": lead,
            "page_title": title,
            "page_lead": lead,
            "empty_label": "FAQs are being updated. Please check back soon.",
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0116_sitecontactsettings"),
    ]

    operations = [
        migrations.CreateModel(
            name="FAQPageCopy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("singleton_id", models.PositiveSmallIntegerField(default=1, editable=False, unique=True)),
                ("meta_title", models.CharField(default="FAQ — Bad Guy Motors", max_length=160)),
                ("meta_description", models.TextField(default="Answers to common questions about Bad Guy Motors.")),
                ("page_title", models.CharField(default="FAQ", max_length=80)),
                ("page_lead", models.TextField(default="Answers to common questions about Bad Guy Motors.")),
                (
                    "empty_label",
                    models.CharField(
                        default="FAQs are being updated. Please check back soon.",
                        max_length=160,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "FAQ page copy",
                "verbose_name_plural": "FAQ page copy",
                "ordering": ("singleton_id",),
            },
        ),
        migrations.RunPython(seed_faq_page_copy, migrations.RunPython.noop),
    ]
