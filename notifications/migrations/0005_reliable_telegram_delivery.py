from django.db import migrations, models


def mark_existing_delivery_results(apps, schema_editor):
    logs = apps.get_model("notifications", "TelegramMessageLog")
    # Historical failures stay visible but are not unexpectedly replayed on deploy.
    logs.objects.filter(success=False).update(status="failed")
    logs.objects.filter(success=True).update(sent_at=models.F("created_at"))


class Migration(migrations.Migration):
    dependencies = [("notifications", "0004_alter_telegrambotsettings_admin_chat_ids")]

    operations = [
        migrations.AddField("telegrammessagelog", "status", models.CharField(choices=[("pending", "Queued"), ("sending", "Sending"), ("sent", "Sent"), ("failed", "Failed; retry scheduled"), ("uncertain", "Delivery unknown; retry scheduled")], default="sent", db_default="sent", max_length=16)),
        migrations.AddField("telegrammessagelog", "dedupe_key", models.CharField(blank=True, max_length=255, null=True)),
        migrations.AddField("telegrammessagelog", "entity_type", models.CharField(blank=True, max_length=64, db_default="")),
        migrations.AddField("telegrammessagelog", "entity_id", models.CharField(blank=True, max_length=80, db_default="")),
        migrations.AddField("telegrammessagelog", "digest_slot", models.CharField(blank=True, max_length=64, db_default="")),
        migrations.AddField("telegrammessagelog", "telegram_message_id", models.BigIntegerField(blank=True, null=True)),
        migrations.AddField("telegrammessagelog", "attempts", models.PositiveIntegerField(default=0, db_default=0)),
        migrations.AddField("telegrammessagelog", "next_attempt_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("telegrammessagelog", "claimed_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("telegrammessagelog", "sent_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddConstraint("telegrammessagelog", models.UniqueConstraint(fields=("chat_id", "dedupe_key"), name="tg_unique_recipient_message")),
        migrations.AddIndex("telegrammessagelog", models.Index(fields=["status", "next_attempt_at"], name="tg_delivery_due_idx")),
        migrations.RunPython(mark_existing_delivery_results, migrations.RunPython.noop),
    ]
