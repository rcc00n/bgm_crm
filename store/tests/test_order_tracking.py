from __future__ import annotations

from django.test import SimpleTestCase

from store.models import Order


class OrderTrackingTests(SimpleTestCase):
    def test_tracking_entries_prefers_printful_payload(self):
        order = Order(
            tracking_numbers="LEGACY-1",
            tracking_url="https://tracking.example/legacy",
            printful_tracking_data=[
                {
                    "number": "TRACK-123",
                    "url": "https://tracking.example/123",
                    "carrier": "UPS",
                    "estimated_delivery": "2026-03-12",
                    "shipment_date": "2026-03-08",
                    "delivery_date": "",
                    "tracking_events": ["2026-03-08T13:00:00Z: In transit"],
                },
                {
                    "number": "TRACK-456",
                    "url": "https://tracking.example/456",
                    "carrier": "FedEx",
                    "estimated_delivery": "",
                    "shipment_date": "",
                    "delivery_date": "",
                    "tracking_events": [],
                },
            ],
        )

        self.assertEqual(
            order.tracking_entries,
            [
                {
                    "number": "TRACK-123",
                    "url": "https://tracking.example/123",
                    "carrier": "UPS",
                    "estimated_delivery": "2026-03-12",
                    "shipment_date": "2026-03-08",
                    "delivery_date": "",
                    "tracking_events": ["2026-03-08T13:00:00Z: In transit"],
                },
                {
                    "number": "TRACK-456",
                    "url": "https://tracking.example/456",
                    "carrier": "FedEx",
                    "estimated_delivery": "",
                    "shipment_date": "",
                    "delivery_date": "",
                    "tracking_events": [],
                },
            ],
        )
        self.assertEqual(order.primary_tracking_url, "https://tracking.example/123")
        self.assertEqual(
            order.shipment_detail_rows(),
            [
                ("Package 1 Tracking", "TRACK-123"),
                ("Package 1 Carrier", "UPS"),
                ("Package 1 Estimated delivery", "2026-03-12"),
                ("Package 1 Shipment date", "2026-03-08"),
                ("Package 2 Tracking", "TRACK-456"),
                ("Package 2 Carrier", "FedEx"),
            ],
        )
        self.assertEqual(
            order.shipment_notice_lines(),
            ["Package 1 event 1: 2026-03-08T13:00:00Z: In transit"],
        )

    def test_tracking_entries_falls_back_to_legacy_fields(self):
        order = Order(
            tracking_numbers="TRACK-123\nTRACK-456",
            tracking_url="https://tracking.example/123",
            printful_tracking_data=[],
        )

        self.assertEqual(
            order.tracking_entries,
            [
                {
                    "number": "TRACK-123",
                    "url": "https://tracking.example/123",
                    "carrier": "",
                    "estimated_delivery": "",
                    "shipment_date": "",
                    "delivery_date": "",
                    "tracking_events": [],
                },
                {
                    "number": "TRACK-456",
                    "url": "https://tracking.example/123",
                    "carrier": "",
                    "estimated_delivery": "",
                    "shipment_date": "",
                    "delivery_date": "",
                    "tracking_events": [],
                },
            ],
        )
