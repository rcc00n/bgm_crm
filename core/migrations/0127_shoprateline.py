from django.db import migrations, models


DEFAULT_RATE_ROWS = (
    ("Mechanical Service", "$140 / hr", 10),
    ("Custom Fabrication", "$145 / hr", 20),
    ("Specialty / European", "$150 / hr", 30),
    ("Design & Engineering", "$150 / hr", 40),
    ("Customer-Supplied Parts", "$145 / hr", 50),
)


def seed_shop_rate_lines(apps, schema_editor):
    ShopRateSettings = apps.get_model("core", "ShopRateSettings")
    ShopRateLine = apps.get_model("core", "ShopRateLine")

    settings_obj, _ = ShopRateSettings.objects.get_or_create(
        singleton_id=1,
        defaults={
            "our_shop_rate": "130/hr",
            "our_design_rate": "150/hr",
        },
    )
    if ShopRateLine.objects.filter(settings=settings_obj).exists():
        return

    ShopRateLine.objects.bulk_create(
        [
            ShopRateLine(
                settings=settings_obj,
                label=label,
                display_rate=display_rate,
                sort_order=sort_order,
            )
            for label, display_rate, sort_order in DEFAULT_RATE_ROWS
        ]
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0126_shopratesettings_our_design_rate"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShopRateLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(max_length=120)),
                ("display_rate", models.CharField(help_text="Shown exactly as entered, for example: $140 / hr", max_length=60)),
                ("sort_order", models.PositiveSmallIntegerField(default=10, help_text="Lower numbers show first.")),
                (
                    "settings",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="rate_rows", to="core.shopratesettings"),
                ),
            ],
            options={
                "verbose_name": "Shop rate line",
                "verbose_name_plural": "Shop rate lines",
                "ordering": ("sort_order", "id"),
            },
        ),
        migrations.RunPython(seed_shop_rate_lines, migrations.RunPython.noop),
    ]
