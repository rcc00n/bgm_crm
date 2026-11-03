from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0129_sitehourssettings")]

    operations = [
        migrations.CreateModel(
            name="LeadReviewCase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("entity_type", models.CharField(choices=[("fitment_request", "Fitment request"), ("service_lead", "Service lead"), ("lead", "Qualification lead")], max_length=40)),
                ("entity_id", models.CharField(max_length=64)),
                ("reasons", models.JSONField(blank=True, default=list)),
                ("known_campaign", models.BooleanField(default=False)),
                ("fingerprint", models.CharField(blank=True, max_length=64)),
                ("status", models.CharField(choices=[("pending", "Pending review"), ("released", "Released"), ("spam", "Marked as spam")], db_index=True, default="pending", max_length=16)),
                ("shop_synced_at", models.DateTimeField(blank=True, null=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Lead review case",
                "verbose_name_plural": "Lead review queue",
                "ordering": ("status", "-created_at"),
                "constraints": [models.UniqueConstraint(fields=("entity_type", "entity_id"), name="unique_lead_review_entity")],
            },
        ),
    ]
