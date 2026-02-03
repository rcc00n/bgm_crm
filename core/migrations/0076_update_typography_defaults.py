from django.db import migrations


def update_typography_defaults(apps, schema_editor):
    FontPreset = apps.get_model("core", "FontPreset")
    PageFontSetting = apps.get_model("core", "PageFontSetting")
    TopbarSettings = apps.get_model("core", "TopbarSettings")

    font_map = {
        font.slug: font
        for font in FontPreset.objects.filter(
            slug__in=["diesel", "ford", "inter"],
            is_active=True,
        )
    }
    diesel = font_map.get("diesel")
    ford = font_map.get("ford")
    inter = font_map.get("inter")

    if not diesel or not inter:
        return

    for setting in PageFontSetting.objects.all():
        if not setting.body_font_id or not setting.heading_font_id:
            continue
        if diesel and ford and setting.body_font_id == diesel.id and setting.heading_font_id == ford.id:
            setting.body_font_id = inter.id
            setting.heading_font_id = diesel.id
            update_fields = ["body_font", "heading_font"]
            if setting.ui_font_id == diesel.id:
                setting.ui_font_id = inter.id
                update_fields.append("ui_font")
            setting.save(update_fields=update_fields)

    for page_slug in ("about", "merch", "project_journal"):
        PageFontSetting.objects.get_or_create(
            page=page_slug,
            defaults={
                "body_font_id": inter.id,
                "heading_font_id": diesel.id,
                "ui_font_id": inter.id,
            },
        )

    topbar = TopbarSettings.objects.first()
    if not topbar:
        return

    update_fields = []
    if topbar.brand_font_id is None or (ford and topbar.brand_font_id == ford.id):
        topbar.brand_font_id = diesel.id
        update_fields.append("brand_font")
    if topbar.nav_font_id is None or (diesel and topbar.nav_font_id == diesel.id):
        topbar.nav_font_id = inter.id
        update_fields.append("nav_font")

    if update_fields:
        topbar.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0075_pagefontsetting_style_overrides"),
    ]

    operations = [
        migrations.RunPython(update_typography_defaults, migrations.RunPython.noop),
    ]
