from django.db import migrations, models


def seed_design_rate(apps, schema_editor):
    ShopRateSettings = apps.get_model("core", "ShopRateSettings")
    ClientPortalPageCopy = apps.get_model("core", "ClientPortalPageCopy")
    AboutPageCopy = apps.get_model("core", "AboutPageCopy")

    design_rate = "150/hr"
    for model in (ClientPortalPageCopy, AboutPageCopy):
        record = model.objects.order_by("id").first()
        if not record:
            continue
        candidate = (getattr(record, "rates_cad_value", "") or "").strip()
        if candidate:
            design_rate = candidate
            break

    settings_obj, _ = ShopRateSettings.objects.get_or_create(
        singleton_id=1,
        defaults={"our_shop_rate": "130/hr"},
    )
    if not (getattr(settings_obj, "our_design_rate", "") or "").strip():
        settings_obj.our_design_rate = design_rate
        settings_obj.save(update_fields=["our_design_rate", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0125_shopratesettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="shopratesettings",
            name="our_design_rate",
            field=models.CharField(
                default="150/hr",
                help_text="Shared design/CAD rate shown in the client portal and public site sections.",
                max_length=40,
            ),
        ),
        migrations.RunPython(seed_design_rate, migrations.RunPython.noop),
    ]
