from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0082_role_notifications_and_email_prefs"),
    ]

    operations = [
        migrations.AddField(
            model_name="topbarsettings",
            name="brand_word_white_font",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional font override for the first brand word.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="topbar_brand_word_white_settings",
                to="core.fontpreset",
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="brand_word_red_font",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional font override for the second brand word.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="topbar_brand_word_red_settings",
                to="core.fontpreset",
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="order_brand",
            field=models.CharField(
                default="1",
                help_text="CSS order for the brand block.",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="order_tagline",
            field=models.CharField(
                default="2",
                help_text="CSS order for the tagline block.",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="order_nav",
            field=models.CharField(
                default="3",
                help_text="CSS order for the navigation block.",
                max_length=8,
            ),
        ),
    ]
