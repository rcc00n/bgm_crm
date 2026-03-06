from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from store.models import Order
from store.printful_fulfillment import (
    _extract_tracking_entries,
    build_printful_recipient_from_form,
    build_printful_webhook_url,
    get_checkout_printful_shipping,
    sync_order_from_printful_payload,
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

    @patch("store.printful_fulfillment._refresh_merch_option_mapping")
    @patch("store.printful_fulfillment.quote_printful_shipping_rates")
    def test_get_checkout_shipping_refreshes_missing_variant_mapping(
        self,
        quote_printful_shipping_rates,
        refresh_merch_option_mapping,
    ):
        quote_printful_shipping_rates.return_value = [
            {
                "id": "STANDARD",
                "name": "Flat Rate",
                "rate": "8.95",
                "currency": "CAD",
            }
        ]
        refresh_merch_option_mapping.return_value = type(
            "MappedOption",
            (),
            {"printful_variant_id": 9988},
        )()

        shipping = get_checkout_printful_shipping(
            positions=[
                {
                    "product": type("P", (), {"category": type("C", (), {"slug": "merch"})(), "sku": "PF-1", "slug": "merch-1", "name": "Bandana"})(),
                    "option": type("O", (), {"printful_variant_id": None})(),
                    "qty": 1,
                }
            ],
            form={
                "address_line1": "4901 46 Ave",
                "city": "Camrose",
                "region": "AB",
                "postal_code": "T4V2R3",
                "country": "Canada",
            },
            require_complete=False,
        )

        self.assertEqual(shipping["selected_rate_id"], "STANDARD")
        self.assertEqual(shipping["shipping_cost"], Decimal("8.95"))
        self.assertEqual(shipping["error"], "")
        refresh_merch_option_mapping.assert_called_once()

    def test_extract_tracking_entries_supports_nested_shipment_payloads(self):
        entries = _extract_tracking_entries(
            {
                "type": "package_shipped",
                "data": {
                    "shipment": {
                        "tracking_number": "TRACK-123",
                        "tracking_url": "https://tracking.example/123",
                        "carrier": "UPS",
                        "estimated_delivery": "2026-03-12",
                        "shipment_date": "2026-03-08",
                        "delivery_date": "",
                        "tracking_events": [
                            {"status": "In transit", "timestamp": "2026-03-08T13:00:00Z"},
                            {"status": "Out for delivery", "timestamp": "2026-03-12T08:15:00Z"},
                        ],
                    }
                },
            }
        )

        self.assertEqual(
            entries,
            [
                {
                    "number": "TRACK-123",
                    "url": "https://tracking.example/123",
                    "carrier": "UPS",
                    "estimated_delivery": "2026-03-12",
                    "shipment_date": "2026-03-08",
                    "delivery_date": "",
                    "tracking_events": [
                        "2026-03-08T13:00:00Z: In transit",
                        "2026-03-12T08:15:00Z: Out for delivery",
                    ],
                }
            ],
        )

    def test_sync_order_from_payload_updates_tracking_fields(self):
        class _FakeOrder:
            def __init__(self):
                self.printful_order_id = None
                self.printful_external_id = ""
                self.printful_status = ""
                self.printful_shipping_cost = Decimal("0.00")
                self.printful_shipping_currency = ""
                self.printful_shipping_name = ""
                self.printful_tracking_data = []
                self.printful_last_synced_at = None
                self.printful_submitted_at = None
                self.printful_error = ""
                self.tracking_numbers = ""
                self.tracking_url = ""
                self.status = Order.STATUS_PROCESSING
                self.shipped_at = None
                self.saved_update_fields = []

            @property
            def tracking_entries(self):
                rows = []
                for entry in self.printful_tracking_data:
                    rows.append({
                        "number": str(entry.get("number") or "").strip(),
                        "url": str(entry.get("url") or "").strip(),
                    })
                return rows

            def save(self, update_fields=None):
                self.saved_update_fields = list(update_fields or [])

        order = _FakeOrder()

        sync_order_from_printful_payload(
            order,
            {
                "id": 148615541,
                "external_id": "bgm-order-123",
                "status": "fulfilled",
                "shipping_service_name": "Flat Rate",
                "costs": {"shipping": "11.95", "currency": "CAD"},
                "result": {
                    "shipment": {
                        "tracking_number": "TRACK-123",
                        "tracking_url": "https://tracking.example/123",
                        "carrier": "UPS",
                        "estimated_delivery": "2026-03-12",
                        "shipment_date": "2026-03-08",
                        "delivery_date": "",
                        "tracking_events": [{"status": "In transit", "timestamp": "2026-03-08T13:00:00Z"}],
                    }
                },
            },
        )

        self.assertEqual(order.printful_order_id, 148615541)
        self.assertEqual(order.printful_status, "fulfilled")
        self.assertEqual(order.printful_shipping_name, "Flat Rate")
        self.assertEqual(order.printful_shipping_cost, Decimal("11.95"))
        self.assertEqual(order.tracking_numbers, "TRACK-123")
        self.assertEqual(order.tracking_url, "https://tracking.example/123")
        self.assertEqual(
            order.printful_tracking_data,
            [
                {
                    "number": "TRACK-123",
                    "url": "https://tracking.example/123",
                    "carrier": "UPS",
                    "estimated_delivery": "2026-03-12",
                    "shipment_date": "2026-03-08",
                    "delivery_date": "",
                    "tracking_events": ["2026-03-08T13:00:00Z: In transit"],
                }
            ],
        )
        self.assertEqual(order.status, Order.STATUS_SHIPPED)
        self.assertIn("tracking_numbers", order.saved_update_fields)
        self.assertIn("tracking_url", order.saved_update_fields)
