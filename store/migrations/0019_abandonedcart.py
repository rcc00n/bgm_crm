from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0018_storepricingsettings_alter_product_price_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AbandonedCart",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("session_key", models.CharField(blank=True, db_index=True, max_length=64)),
                ("email", models.EmailField(db_index=True, max_length=254)),
                ("cart_items", models.JSONField(default=list)),
                ("cart_total", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("currency_code", models.CharField(blank=True, max_length=8)),
                ("currency_symbol", models.CharField(blank=True, max_length=8)),
                ("last_activity_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("recovered_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("email_1_sent_at", models.DateTimeField(blank=True, null=True)),
                ("email_2_sent_at", models.DateTimeField(blank=True, null=True)),
                ("email_3_sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="abandoned_carts",
                        to="auth.user",
                    ),
                ),
            ],
            options={
                "verbose_name": "Abandoned cart",
                "verbose_name_plural": "Abandoned carts",
                "ordering": ("-created_at",),
            },
        ),
    ]
