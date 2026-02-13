from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0104_remove_coming_soon_copy"),
    ]

    operations = [
        migrations.AddField(
            model_name="storepagecopy",
            name="fitment_success_message",
            field=models.CharField(
                default="Hi {customer_name}, thanks for submitting your custom fitment request. We got it and will reach out soon.",
                help_text="Green success message on product page after fitment form submit. Use {customer_name} token.",
                max_length=280,
            ),
        ),
    ]
