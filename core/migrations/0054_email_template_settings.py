from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0053_email_templates"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailTemplateSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("singleton_id", models.PositiveSmallIntegerField(default=1, editable=False, unique=True)),
                (
                    "brand_name",
                    models.CharField(
                        blank=True,
                        help_text="Optional override for SITE_BRAND_NAME when sending emails.",
                        max_length=120,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Email template settings",
                "verbose_name_plural": "Email template settings",
                "ordering": ("singleton_id",),
            },
        ),
    ]
