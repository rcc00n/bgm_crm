from django.db import migrations, models


def seed_admin_login_branding(apps, schema_editor):
    AdminLoginBranding = apps.get_model("core", "AdminLoginBranding")
    AdminLoginBranding.objects.get_or_create(singleton_id=1)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0062_rename_core_adminsi_user_model_idx_core_admins_user_id_31d4ba_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="AdminLoginBranding",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("singleton_id", models.PositiveSmallIntegerField(default=1, editable=False, unique=True)),
                (
                    "login_logo",
                    models.ImageField(
                        blank=True,
                        help_text="Logo shown on the admin login screen.",
                        null=True,
                        upload_to="admin/branding/",
                    ),
                ),
                (
                    "login_logo_dark",
                    models.ImageField(
                        blank=True,
                        help_text="Optional dark mode logo for the admin login screen.",
                        null=True,
                        upload_to="admin/branding/",
                    ),
                ),
                (
                    "login_logo_alt",
                    models.CharField(
                        default="Admin logo",
                        help_text="Accessible alt text for the login logo.",
                        max_length=120,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Admin login branding",
                "verbose_name_plural": "Admin login branding",
                "ordering": ("singleton_id",),
            },
        ),
        migrations.RunPython(seed_admin_login_branding, migrations.RunPython.noop),
    ]
