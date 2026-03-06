from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from store.printful_fulfillment import (
    build_printful_recipient_from_form,
    build_printful_webhook_url,
    get_checkout_printful_shipping,
)


@override_settings(COMPANY_WEBSITE="https://badguymotors.com", PRINTFUL_WEBHOOK_SECRET="secret-123")
class PrintfulFulfillmentHelperTests(SimpleTestCase):
    def test_build_printful_recipient_from_form_normalizes_codes(self):
        recipient, errors = build_printful_recipient_from_form(
            {
                "customer_name": "Test User",
                "email": "test@example.com",
                "phone": "+1 403 555 1234",
                "address_line1": "123 Main St",
                "address_line2": "Unit 2",
                "city": "Medicine Hat",
                "region": "Alberta",
                "postal_code": "T1A0A1",
                "country": "Canada",
            }
        )

        self.assertEqual(errors, {})
        self.assertEqual(recipient["state_code"], "AB")
        self.assertEqual(recipient["country_code"], "CA")
        self.assertEqual(recipient["zip"], "T1A 0A1")
        self.assertEqual(recipient["address2"], "Unit 2")

    def test_build_printful_webhook_url_uses_configured_secret(self):
        url = build_printful_webhook_url()

        self.assertEqual(url, "https://badguymotors.com/store/printful/webhook/secret-123/")

    @patch("store.printful_fulfillment.quote_printful_shipping_rates")
    def test_get_checkout_shipping_allows_quote_before_contact_fields(self, quote_printful_shipping_rates):
        quote_printful_shipping_rates.return_value = [
            {
                "id": "STANDARD",
                "name": "Flat Rate",
                "rate": "11.95",
                "currency": "CAD",
                "min_delivery_date": "2026-03-13",
                "max_delivery_date": "2026-03-16",
            }
        ]

        shipping = get_checkout_printful_shipping(
            positions=[
                {
                    "product": type("P", (), {"category": type("C", (), {"slug": "merch"})(), "sku": "PF-1", "slug": "merch-1", "name": "Merch Tee"})(),
                    "option": type("O", (), {"printful_variant_id": 18730})(),
                    "qty": 1,
                }
            ],
            form={
                "customer_name": "",
                "email": "",
                "phone": "",
                "address_line1": "4901 46 Ave",
                "address_line2": "No unit",
                "city": "Camrose",
                "region": "AB",
                "postal_code": "T4V2R3",
                "country": "Canada",
            },
            require_complete=False,
        )

        self.assertEqual(shipping["selected_rate_id"], "STANDARD")
        self.assertEqual(shipping["shipping_cost"], Decimal("11.95"))
        self.assertEqual(shipping["error"], "")
        quote_printful_shipping_rates.assert_called_once()
