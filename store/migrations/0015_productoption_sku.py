from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0014_order_payment_amount_order_payment_balance_due_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="productoption",
            name="sku",
            field=models.CharField(blank=True, max_length=64, null=True, unique=True, verbose_name="SKU"),
        ),
    ]
