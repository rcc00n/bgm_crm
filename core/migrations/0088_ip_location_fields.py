from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0087_admin_notification_prefs"),
    ]

    operations = [
        migrations.AddField(
            model_name="leadsubmissionevent",
            name="ip_location",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="visitorsession",
            name="ip_location",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
