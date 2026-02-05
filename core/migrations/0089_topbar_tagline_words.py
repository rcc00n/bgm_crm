from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0088_ip_location_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_1_text",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional override for the first tagline word.",
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_2_text",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional override for the second tagline word.",
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_3_text",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional override for the third tagline word.",
                max_length=40,
            ),
        ),
    ]
