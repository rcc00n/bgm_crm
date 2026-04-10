from django.db import migrations, models


def seed_shop_rate_settings(apps, schema_editor):
    ShopRateSettings = apps.get_model("core", "ShopRateSettings")
    ClientPortalPageCopy = apps.get_model("core", "ClientPortalPageCopy")
    AboutPageCopy = apps.get_model("core", "AboutPageCopy")

    shop_rate = "130/hr"
    for model in (ClientPortalPageCopy, AboutPageCopy):
        record = model.objects.order_by("id").first()
        if not record:
            continue
        candidate = (getattr(record, "rates_shop_value", "") or "").strip()
        if candidate:
            shop_rate = candidate
            break

    ShopRateSettings.objects.get_or_create(
        singleton_id=1,
        defaults={"our_shop_rate": shop_rate},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0124_shopshareddatarecord"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShopRateSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("singleton_id", models.PositiveSmallIntegerField(default=1, editable=False, unique=True)),
                ("our_shop_rate", models.CharField(default="130/hr", help_text="Shared shop rate shown in the client portal and public site sections.", max_length=40)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Shop rate settings",
                "verbose_name_plural": "Shop rate settings",
                "ordering": ("singleton_id",),
            },
        ),
        migrations.RunPython(seed_shop_rate_settings, migrations.RunPython.noop),
    ]
