from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from store.management.commands.sync_bgm_pricing import Command, PricingRow
from store.models import Category, ImportBatch, Product


class SyncBgmPricingCommandTests(TestCase):
    def setUp(self):
        self.command = Command()
        self.batch = ImportBatch.objects.create(
            source_filename="test.csv",
            mode="sync-bgm-pricing",
        )

    def test_deactivate_obsolete_turns_off_legacy_rear_bumper_cards(self):
        legacy_category = Category.objects.create(name="Bumpers", slug="bumpers")
        misc_category = Category.objects.create(name="Misc", slug="misc")
        legacy = Product.objects.create(
            name="Rear Bumpers - Smooth Liner",
            slug="rear-bumpers-smooth-liner",
            sku="BGM-SCL-REARB",
            category=legacy_category,
            price=Decimal("1999.00"),
            is_in_house=True,
            is_active=True,
        )
        unrelated = Product.objects.create(
            name="BGM Legacy Accessory",
            slug="bgm-legacy-accessory",
            sku="BGM-LEGACY-ACCESSORY",
            category=misc_category,
            price=Decimal("99.00"),
            is_in_house=True,
            is_active=True,
        )

        summary = self.command._sync_catalog(
            grouped_rows={
                "Rear Bumper": [
                    PricingRow(
                        sku="BGM-SCL-REARB",
                        category="Rear Bumper",
                        description="Base",
                        finish="SCL",
                        size_class="2500/3500",
                        unit="Each",
                        msrp=Decimal("2200.00"),
                        tier_1_price=Decimal("2000.00"),
                        tier_2_price=Decimal("1800.00"),
                    )
                ]
            },
            batch=self.batch,
            deactivate_obsolete=True,
        )

        legacy.refresh_from_db()
        unrelated.refresh_from_db()
        catalog_product = Product.objects.get(sku="BGM-REAR-BUMPER-CATALOG")

        self.assertEqual(summary["created_products"], 1)
        self.assertFalse(legacy.is_active)
        self.assertEqual(legacy.import_batch_id, self.batch.id)
        self.assertTrue(unrelated.is_active)
        self.assertTrue(catalog_product.is_active)
        self.assertEqual(catalog_product.dealer_tier_1_price, Decimal("2000.00"))

    def test_sync_catalog_assigns_best_fit_image_when_catalog_product_is_blank(self):
        donor_category = Category.objects.create(name="Running Boards", slug="running-boards")
        Product.objects.create(
            name="Running Boards/ Step Bars",
            slug="running-boards-step-bars",
            sku="BGM-RUNNING-BOARDS-DONOR",
            category=donor_category,
            price=Decimal("899.00"),
            is_in_house=True,
            is_active=True,
            main_image="store/products/photo_2025-08-22_06-57-57_2.jpg",
        )

        self.command._sync_catalog(
            grouped_rows={
                "Badland Bar": [
                    PricingRow(
                        sku="BGM-BADLAND-BAR-ROW",
                        category="Badland Bar",
                        description="Cab Length",
                        finish="ARM",
                        size_class="Vehicle Specific",
                        unit="Each",
                        msrp=Decimal("1200.00"),
                        tier_1_price=Decimal("1100.00"),
                        tier_2_price=Decimal("1000.00"),
                    )
                ]
            },
            batch=self.batch,
            deactivate_obsolete=False,
        )

        catalog_product = Product.objects.get(sku="BGM-BADLAND-BAR-CATALOG")
        self.assertEqual(catalog_product.main_image_name, "store/products/photo_2025-08-22_06-57-57_2.jpg")
