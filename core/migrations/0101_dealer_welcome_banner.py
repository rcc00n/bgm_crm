from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0100_dealerapplication_authorized_signature_date_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="dealerstatuspagecopy",
            name="dealer_welcome_callout",
            field=models.TextField(
                default=(
                    "Congratulations, you're officially a Bad Guy Motors Dealer. "
                    "Your wholesale pricing is now active."
                )
            ),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="dealer_welcome_seen",
            field=models.BooleanField(
                default=True,
                help_text="Internal flag used to show the approval success banner once.",
                verbose_name="Dealer welcome notice seen",
            ),
        ),
    ]

