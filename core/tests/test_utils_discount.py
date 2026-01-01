from decimal import Decimal

from django.test import SimpleTestCase

from core.utils import apply_dealer_discount, dealer_discount_savings


class DealerDiscountTests(SimpleTestCase):
    def test_apply_dealer_discount_reduces_price(self):
        self.assertEqual(apply_dealer_discount("100", 10), Decimal("90.00"))

    def test_apply_dealer_discount_handles_zero_percent(self):
        self.assertEqual(apply_dealer_discount("100", 0), Decimal("100.00"))

    def test_dealer_discount_savings_returns_difference(self):
        self.assertEqual(dealer_discount_savings("200", 25), Decimal("50.00"))
