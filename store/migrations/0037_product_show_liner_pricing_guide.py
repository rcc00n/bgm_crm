from django.db import migrations, models


def enable_liner_pricing_guide_for_inhouse_non_merch(apps, schema_editor):
    Product = apps.get_model("store", "Product")

    qs = Product.objects.filter(is_in_house=True).exclude(category__slug="merch")
    qs = qs.exclude(slug__startswith="merch-").exclude(sku__startswith="PF-")
    qs.update(show_liner_pricing_guide=True)


def disable_liner_pricing_guide_for_inhouse_non_merch(apps, schema_editor):
    Product = apps.get_model("store", "Product")

    qs = Product.objects.filter(is_in_house=True).exclude(category__slug="merch")
    qs = qs.exclude(slug__startswith="merch-").exclude(sku__startswith="PF-")
    qs.update(show_liner_pricing_guide=False)


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0036_storeinventorysettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="show_liner_pricing_guide",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Display a customer-facing finish guide on the product page that explains "
                    "how Armadillo and Smooth Criminal Liner pricing is presented."
                ),
                verbose_name="Show Armadillo vs Smooth Criminal guide",
            ),
        ),
        migrations.RunPython(
            enable_liner_pricing_guide_for_inhouse_non_merch,
            disable_liner_pricing_guide_for_inhouse_non_merch,
        ),
    ]
