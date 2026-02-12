from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0024_alter_product_main_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="customfitmentrequest",
            name="reference_image",
            field=models.ImageField(
                blank=True,
                help_text="Optional customer reference photo for fitment context.",
                null=True,
                upload_to="store/fitment_attachments/",
            ),
        ),
    ]
