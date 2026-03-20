from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from store.models import (
    Category,
    Product,
    ProductDiscount,
    ProductOption,
    StorePricingSettings,
    StoreShippingSettings,
    apply_store_price_multiplier,
)


class StorePricingSettingsTests(SimpleTestCase):
    @patch.object(StorePricingSettings, "load", return_value=None)
    def test_default_multiplier_percent_and_multiplier_when_missing(self, _mock_load):
        self.assertEqual(StorePricingSettings.get_multiplier_percent(), 100)
        self.assertEqual(StorePricingSettings.get_multiplier(), Decimal("1"))

    @patch.object(
        StorePricingSettings,
        "load",
        return_value=StorePricingSettings(price_multiplier_percent=125),
    )
    def test_get_multiplier_uses_loaded_percent(self, _mock_load):
        self.assertEqual(StorePricingSettings.get_multiplier_percent(), 125)
        self.assertEqual(StorePricingSettings.get_multiplier(), Decimal("1.25"))

    @patch.object(StorePricingSettings, "get_multiplier", return_value=Decimal("1.25"))
    def test_apply_store_price_multiplier_uses_saved_percent(self, _mock_multiplier):
        self.assertEqual(apply_store_price_multiplier(Decimal("10.00")), Decimal("12.50"))

    @patch.object(StorePricingSettings, "get_multiplier", return_value=Decimal("1.25"))
    def test_apply_store_price_multiplier_can_bypass_multiplier(self, _mock_multiplier):
        self.assertEqual(
            apply_store_price_multiplier(Decimal("10.00"), apply_multiplier=False),
            Decimal("10.00"),
        )

    def test_apply_store_price_multiplier_invalid_amount_returns_zero(self):
        self.assertEqual(apply_store_price_multiplier("bad-input"), Decimal("0.00"))


class StoreShippingSettingsTests(SimpleTestCase):
    @patch.object(StoreShippingSettings, "load", return_value=None)
    def test_free_shipping_threshold_returns_none_without_settings(self, _mock_load):
        self.assertIsNone(StoreShippingSettings.get_free_shipping_threshold_cad())

    @patch.object(
        StoreShippingSettings,
        "load",
        return_value=StoreShippingSettings(free_shipping_threshold_cad=Decimal("0.00")),
    )
    def test_free_shipping_threshold_treats_zero_as_disabled(self, _mock_load):
        self.assertIsNone(StoreShippingSettings.get_free_shipping_threshold_cad())

    @patch.object(
        StoreShippingSettings,
        "load",
        return_value=StoreShippingSettings(
            free_shipping_threshold_cad=Decimal("200.00"),
            delivery_cost_under_threshold_cad=Decimal("24.5"),
        ),
    )
    def test_delivery_cost_returns_quantized_positive_value(self, _mock_load):
        self.assertEqual(
            StoreShippingSettings.get_delivery_cost_under_threshold_cad(),
            Decimal("24.50"),
        )


class ProductPricingTests(SimpleTestCase):
    def _create_product(self, **overrides) -> Product:
        defaults = {
            "name": "Test Product",
            "slug": "test-product",
            "sku": "SKU-1",
            "category": Category(name="Lift Kits", slug="lift-kits"),
            "price": Decimal("100.00"),
            "is_in_house": False,
        }
        defaults.update(overrides)
        return Product(**defaults)

    def _with_prefetched_options(self, product: Product, *options: ProductOption) -> Product:
        product._prefetched_objects_cache = {"options": list(options)}
        return product

    def _with_prefetched_discounts(self, product: Product, *discounts: ProductDiscount) -> Product:
        cache = getattr(product, "_prefetched_objects_cache", {})
        cache["discounts"] = list(discounts)
        product._prefetched_objects_cache = cache
        return product

    @patch.object(StorePricingSettings, "get_multiplier", return_value=Decimal("1.25"))
    def test_get_unit_price_applies_multiplier_to_non_in_house_product(self, _mock_multiplier):
        product = self._create_product(is_in_house=False)

        self.assertEqual(product.get_unit_price(), Decimal("125.00"))

    @patch.object(StorePricingSettings, "get_multiplier", return_value=Decimal("1.25"))
    def test_get_unit_price_skips_multiplier_for_in_house_product(self, _mock_multiplier):
        product = self._create_product(is_in_house=True)

        self.assertEqual(product.get_unit_price(), Decimal("100.00"))

    @patch.object(StorePricingSettings, "get_multiplier", return_value=Decimal("1"))
    def test_display_price_prefers_cheapest_active_selectable_option(self, _mock_multiplier):
        product = self._create_product(price=Decimal("120.00"))
        option_large = ProductOption(
            product=product,
            name="Large",
            sku="SKU-LARGE",
            price=Decimal("150.00"),
            is_active=True,
            sort_order=1,
        )
        option_small = ProductOption(
            product=product,
            name="Small",
            sku="SKU-SMALL",
            price=Decimal("90.00"),
            is_active=True,
            sort_order=2,
        )
        self._with_prefetched_options(product, option_large, option_small)

        self.assertEqual(product.display_price, Decimal("90.00"))

    def test_has_option_price_overrides_ignores_inactive_and_separator_options(self):
        product = self._create_product()
        inactive = ProductOption(
            product=product,
            name="Inactive",
            sku="SKU-INACTIVE",
            price=Decimal("80.00"),
            is_active=False,
        )
        divider = ProductOption(
            product=product,
            name="Divider",
            sku="SKU-DIVIDER",
            price=Decimal("70.00"),
            is_active=True,
            is_separator=True,
        )
        self._with_prefetched_options(product, inactive, divider)

        self.assertFalse(product.has_option_price_overrides)

    @patch.object(StorePricingSettings, "get_multiplier", return_value=Decimal("1"))
    def test_discounted_pricing_exposes_old_price_when_discount_active(self, _mock_multiplier):
        product = self._create_product(price=Decimal("100.00"))
        today = timezone.now().date()
        discount = ProductDiscount(
            product=product,
            discount_percent=15,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
        )
        self._with_prefetched_options(product)
        self._with_prefetched_discounts(product, discount)

        self.assertEqual(product.get_discounted_display_price(), Decimal("85.00"))
        self.assertEqual(product.old_price, Decimal("100.00"))
        self.assertEqual(product.active_discount_percent, 15)

    @patch.object(StorePricingSettings, "get_multiplier", return_value=Decimal("1"))
    def test_contact_for_estimate_suppresses_discounted_display_price(self, _mock_multiplier):
        product = self._create_product(price=Decimal("100.00"), contact_for_estimate=True)
        today = timezone.now().date()
        discount = ProductDiscount(
            product=product,
            discount_percent=20,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
        )
        self._with_prefetched_options(product)
        self._with_prefetched_discounts(product, discount)

        self.assertEqual(product.get_discounted_display_price(), Decimal("100.00"))
        self.assertIsNone(product.old_price)
