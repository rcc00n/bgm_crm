from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0119_alter_leadsubmissionevent_form_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="AdminReleaseSeen",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("last_seen_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=models.CASCADE,
                        related_name="admin_release_seen",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="adminreleaseseen",
            index=models.Index(fields=["user", "last_seen_at"], name="core_adminr_user_id_508eb2_idx"),
        ),
    ]
