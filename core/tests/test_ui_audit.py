from django.test import SimpleTestCase

from core.services.ui_audit import _is_skip_url


class ClientUiAuditSkipRulesTests(SimpleTestCase):
    def test_post_only_store_endpoints_are_skipped(self):
        self.assertTrue(_is_skip_url("/store/cart/promo/"))
        self.assertTrue(_is_skip_url("/store/checkout/printful-shipping-rates/"))

    def test_normal_store_pages_are_not_skipped(self):
        self.assertFalse(_is_skip_url("/store/cart/"))
        self.assertFalse(_is_skip_url("/store/checkout/"))
