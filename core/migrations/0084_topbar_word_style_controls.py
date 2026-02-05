from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0083_topbar_word_fonts_and_order"),
    ]

    operations = [
        migrations.AddField(
            model_name="topbarsettings",
            name="brand_word_middle_font",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional font override for the middle brand word.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="topbar_brand_word_middle_settings",
                to="core.fontpreset",
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_1_font",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional font override for the first tagline word.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="topbar_tagline_word_1_settings",
                to="core.fontpreset",
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_2_font",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional font override for the second tagline word.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="topbar_tagline_word_2_settings",
                to="core.fontpreset",
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_3_font",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional font override for the third tagline word.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="topbar_tagline_word_3_settings",
                to="core.fontpreset",
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="brand_word_1_color",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS color for the first brand word.",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="brand_word_2_color",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS color for the second brand word.",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="brand_word_3_color",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS color for the third brand word.",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="brand_word_1_size",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-size for the first brand word.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="brand_word_2_size",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-size for the second brand word.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="brand_word_3_size",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-size for the third brand word.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="brand_word_1_weight",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-weight for the first brand word.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="brand_word_2_weight",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-weight for the second brand word.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="brand_word_3_weight",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-weight for the third brand word.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="brand_word_1_style",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-style for the first brand word (normal/italic).",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="brand_word_2_style",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-style for the second brand word (normal/italic).",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="brand_word_3_style",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-style for the third brand word (normal/italic).",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_1_color",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS color for the first tagline word.",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_2_color",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS color for the second tagline word.",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_3_color",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS color for the third tagline word.",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_1_size",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-size for the first tagline word.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_2_size",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-size for the second tagline word.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_3_size",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-size for the third tagline word.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_1_weight",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-weight for the first tagline word.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_2_weight",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-weight for the second tagline word.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_3_weight",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-weight for the third tagline word.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_1_style",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-style for the first tagline word (normal/italic).",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_2_style",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-style for the second tagline word (normal/italic).",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="topbarsettings",
            name="tagline_word_3_style",
            field=models.CharField(
                blank=True,
                default="",
                help_text="CSS font-style for the third tagline word (normal/italic).",
                max_length=16,
            ),
        ),
    ]
