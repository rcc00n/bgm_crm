from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0052_homepagecopy_hero_logo_homepagecopy_hero_logo_alt_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AdminSidebarSeen",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("app_label", models.CharField(max_length=100)),
                ("model_name", models.CharField(max_length=100)),
                ("last_seen_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="admin_sidebar_seen",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "unique_together": {("user", "app_label", "model_name")},
            },
        ),
        migrations.AddIndex(
            model_name="adminsidebarseen",
            index=models.Index(fields=["user", "app_label", "model_name"], name="core_adminsi_user_model_idx"),
        ),
    ]
