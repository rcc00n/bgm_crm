from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0015_productoption_sku"),
    ]

    operations = [
        migrations.CreateModel(
            name="ImportBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("source_filename", models.CharField(blank=True, max_length=255)),
                ("mode", models.CharField(blank=True, max_length=32)),
                ("is_dry_run", models.BooleanField(default=False)),
                ("created_products", models.PositiveIntegerField(default=0)),
                ("updated_products", models.PositiveIntegerField(default=0)),
                ("skipped_products", models.PositiveIntegerField(default=0)),
                ("created_options", models.PositiveIntegerField(default=0)),
                ("updated_options", models.PositiveIntegerField(default=0)),
                ("skipped_options", models.PositiveIntegerField(default=0)),
                ("created_categories", models.PositiveIntegerField(default=0)),
                ("error_count", models.PositiveIntegerField(default=0)),
                ("rolled_back_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="import_batches",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddField(
            model_name="product",
            name="import_batch",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="products",
                to="store.importbatch",
            ),
        ),
        migrations.AddField(
            model_name="productoption",
            name="import_batch",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="options",
                to="store.importbatch",
            ),
        ),
    ]
