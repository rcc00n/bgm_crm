from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from store.management.commands.optimize_supplier_catalog import FAMILY_RULES, Command, _group_sku
from store.models import Category, CleanupBatch, Product, ProductOption


class OptimizeSupplierCatalogCommandTests(TestCase):
    def setUp(self):
        self.command = Command()
        self.batch = CleanupBatch.objects.create(criteria="test cleanup")

    def test_groups_supplier_family_into_parent_with_options(self):
        category = Category.objects.create(name="Motor Vehicle Engine Parts", slug="motor-vehicle-engine-parts")
        Product.objects.create(
            name="EZ Lynk Tune Files 2019+ Ram Cummins",
            slug="ez-lynk-tune-files-2019-ram-cummins",
            sku="EZLYNK-CUMMINS-2019",
            category=category,
            price=Decimal("899.00"),
            inventory=3,
            is_active=True,
            is_in_house=False,
            short_description="2019+ Ram tuning",
            main_image="store/imports/catalog/ez-lynk-cummins-a.jpg",
        )
        Product.objects.create(
            name="EZ Lynk Tune Files 2022+ Ram Cummins",
            slug="ez-lynk-tune-files-2022-ram-cummins",
            sku="EZLYNK-CUMMINS-2022",
            category=category,
            price=Decimal("949.00"),
            inventory=4,
            is_active=True,
            is_in_house=False,
            short_description="2022+ Ram tuning",
            main_image="store/imports/catalog/ez-lynk-cummins-b.jpg",
        )

        summary = self.command._run_cleanup(batch=self.batch, apply_changes=True)

        rule = next(rule for rule in FAMILY_RULES if rule.prefix == "EZ Lynk Tune Files")
        parent = Product.objects.get(sku=_group_sku(rule, "cummins"))

        self.assertTrue(parent.is_active)
        self.assertFalse(parent.is_in_house)
        self.assertEqual(parent.inventory, 7)
        self.assertEqual(parent.price, Decimal("899.00"))
        self.assertEqual(parent.main_image.name, "store/imports/catalog/ez-lynk-cummins-b.jpg")
        self.assertEqual(parent.options.filter(is_active=True).count(), 2)
        self.assertEqual(
            list(parent.options.filter(is_active=True).values_list("name", flat=True)),
            ["2019+ Ram Cummins", "2022+ Ram Cummins"],
        )
        self.assertEqual(
            Product.objects.filter(
                sku__in=["EZLYNK-CUMMINS-2019", "EZLYNK-CUMMINS-2022"],
                is_active=False,
                cleanup_batch=self.batch,
            ).count(),
            2,
        )
        category.refresh_from_db()
        self.assertEqual(category.image.name, "store/imports/catalog/ez-lynk-cummins-b.jpg")
        self.assertEqual(summary["created_options"], 2)
        self.assertEqual(summary["deactivated_products"], 2)

    def test_dedupes_exact_copies_and_moves_duplicate_options(self):
        category = Category.objects.create(name="FASS Parts, Pumps & Filters", slug="fass-parts-pumps-filters")
        Product.objects.create(
            name="FASS Base Spring",
            slug="fass-base-spring-a",
            sku="FASS-BASE-SPRING-A",
            category=category,
            price=Decimal("19.00"),
            inventory=2,
            is_active=True,
            is_in_house=False,
        )
        duplicate = Product.objects.create(
            name="FASS Base Spring",
            slug="fass-base-spring-b",
            sku="FASS-BASE-SPRING-B",
            category=category,
            price=Decimal("17.00"),
            inventory=5,
            is_active=True,
            is_in_house=False,
            short_description="Supplier duplicate with better image",
            main_image="store/imports/catalog/fass-base-spring.jpg",
        )
        ProductOption.objects.create(
            product=duplicate,
            name="Red Spring",
            sku="FASS-BASE-SPRING-B-RED",
            price=Decimal("17.00"),
            is_active=True,
        )

        summary = self.command._run_cleanup(batch=self.batch, apply_changes=True)

        active_product = Product.objects.get(name="FASS Base Spring", is_active=True)
        self.assertEqual(Product.objects.filter(name="FASS Base Spring", is_active=False, cleanup_batch=self.batch).count(), 1)
        self.assertEqual(active_product.price, Decimal("17.00"))
        self.assertEqual(active_product.inventory, 7)
        self.assertEqual(active_product.main_image.name, "store/imports/catalog/fass-base-spring.jpg")
        self.assertTrue(active_product.options.filter(name="Red Spring", is_active=True).exists())
        self.assertEqual(summary["duplicate_groups"], 1)
        self.assertEqual(summary["deactivated_products"], 1)

    def test_uses_global_catalog_image_when_category_has_no_local_donor(self):
        donor_category = Category.objects.create(name="BGM Donor", slug="bgm-donor")
        Product.objects.create(
            name="BGM Donor Product",
            slug="bgm-donor-product",
            sku="BGM-DONOR",
            category=donor_category,
            price=Decimal("99.00"),
            inventory=1,
            is_active=True,
            is_in_house=True,
            main_image="store/products/bgm-donor.jpg",
        )
        blank_category = Category.objects.create(name="Blank Category", slug="blank-category")
        Product.objects.create(
            name="Blank Category Product",
            slug="blank-category-product",
            sku="BLANK-CATEGORY-1",
            category=blank_category,
            price=Decimal("39.00"),
            inventory=1,
            is_active=True,
            is_in_house=False,
        )

        summary = self.command._run_cleanup(batch=self.batch, apply_changes=True)

        blank_category.refresh_from_db()
        self.assertEqual(blank_category.image.name, "store/products/bgm-donor.jpg")
        self.assertEqual(summary["filled_category_images"], 2)
