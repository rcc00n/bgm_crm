from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0086_project_journal_photos"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="admin_notification_disabled_sections",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Admin notification section keys disabled for this user.",
            ),
        ),
    ]
