from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0019_abandonedcart"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="review_request_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
