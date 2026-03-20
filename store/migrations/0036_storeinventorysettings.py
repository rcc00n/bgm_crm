from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0035_alter_product_printful_product_id_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="StoreInventorySettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "low_stock_threshold",
                    models.PositiveIntegerField(
                        default=5,
                        help_text=(
                            "Products with inventory at or below this number are highlighted as low stock in admin. "
                            "Set to 0 to disable low-stock alerts."
                        ),
                        verbose_name="Low stock threshold",
                    ),
                ),
                (
                    "allow_out_of_stock_orders",
                    models.BooleanField(
                        default=True,
                        help_text="When disabled, customers cannot add products with zero inventory to the cart or checkout them.",
                        verbose_name="Allow out-of-stock orders",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Store inventory settings",
                "verbose_name_plural": "Store inventory settings",
            },
        ),
    ]
