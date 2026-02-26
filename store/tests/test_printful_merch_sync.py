from decimal import Decimal

from django.test import TestCase, override_settings

from accounts.views import _sync_printful_merch_products
from store.models import Category, Product


class PrintfulMerchSyncTests(TestCase):
    def setUp(self):
        self.merch_category = Category.objects.create(name="Merch", slug="merch")
        self.other_category = Category.objects.create(name="Other", slug="other")

    def _create_pf_product(self, product_id: int, *, price: str = "50.00", is_active: bool = True) -> Product:
        return Product.objects.create(
            name=f"PF {product_id}",
            slug=f"pf-{product_id}",
            sku=f"PF-{product_id}",
            category=self.merch_category,
            price=Decimal(price),
            is_active=is_active,
        )

    def _sync_payload(self, product_id: int, *, base_price: str = "19.99") -> list[dict]:
        return [
            {
                "id": product_id,
                "name": f"Synced {product_id}",
                "base_price": base_price,
                "currency": "CAD",
                "image_url": "",
                "category_label": "T-Shirts",
                "variants": [{"id": 1, "name": "Default", "price": base_price, "sku": f"PF-{product_id}-1"}],
            }
        ]

    @override_settings(PRINTFUL_MERCH_LIMIT=0)
    def test_full_sync_deactivates_removed_products(self):
        kept = self._create_pf_product(101, price="40.00")
        removed = self._create_pf_product(202, price="60.00")
        non_printful = Product.objects.create(
            name="Local Product",
            slug="local-product",
            sku="LOCAL-1",
            category=self.other_category,
            price=Decimal("25.00"),
            is_active=True,
        )

        _sync_printful_merch_products(self._sync_payload(101, base_price="19.99"))

        kept.refresh_from_db()
        removed.refresh_from_db()
        non_printful.refresh_from_db()

        self.assertTrue(kept.is_active)
        self.assertEqual(kept.price, Decimal("19.99"))
        self.assertFalse(removed.is_active)
        self.assertTrue(non_printful.is_active)

    @override_settings(PRINTFUL_MERCH_LIMIT=8)
    def test_limited_sync_keeps_missing_products_active(self):
        self._create_pf_product(101, price="40.00")
        missing_but_kept = self._create_pf_product(202, price="60.00")

        _sync_printful_merch_products(self._sync_payload(101, base_price="21.00"))

        missing_but_kept.refresh_from_db()
        self.assertTrue(missing_but_kept.is_active)
