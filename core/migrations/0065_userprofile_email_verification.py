from django.db import migrations, models
from django.utils import timezone


def mark_existing_profiles_verified(apps, schema_editor):
    UserProfile = apps.get_model("core", "UserProfile")
    now = timezone.now()
    UserProfile.objects.filter(email_verified_at__isnull=True).update(email_verified_at=now)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0064_emailcampaign_emailcampaignrecipient_emailsubscriber_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="email_verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="email_verification_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(mark_existing_profiles_verified, migrations.RunPython.noop),
    ]
