from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from store.printful_fulfillment import build_printful_recipient_from_form, build_printful_webhook_url


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
