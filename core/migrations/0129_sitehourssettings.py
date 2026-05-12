from django.conf import settings
from django.db import migrations, models


DEFAULT_HOURS = "Monday - Friday: 8:00 AM - 4:30 PM"


def seed_site_hours_settings(apps, schema_editor):
    SiteHoursSettings = apps.get_model("core", "SiteHoursSettings")
    hours_text = (getattr(settings, "COMPANY_HOURS", "") or DEFAULT_HOURS).strip()
    SiteHoursSettings.objects.get_or_create(
        singleton_id=1,
        defaults={"hours_text": hours_text},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0128_remove_dealertierlevel_discount_percent_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="SiteHoursSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("singleton_id", models.PositiveSmallIntegerField(default=1, editable=False, unique=True)),
                ("hours_text", models.TextField(blank=True, default=DEFAULT_HOURS, help_text="One line per row, exactly as it should appear on the website.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Site hours settings",
                "verbose_name_plural": "Site hours settings",
                "ordering": ("singleton_id",),
            },
        ),
        migrations.RunPython(seed_site_hours_settings, migrations.RunPython.noop),
    ]
