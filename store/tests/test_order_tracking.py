from __future__ import annotations

from django.test import SimpleTestCase

from store.models import Order


class OrderTrackingTests(SimpleTestCase):
    def test_tracking_entries_prefers_printful_payload(self):
        order = Order(
            tracking_numbers="LEGACY-1",
            tracking_url="https://tracking.example/legacy",
            printful_tracking_data=[
                {"number": "TRACK-123", "url": "https://tracking.example/123"},
                {"number": "TRACK-456", "url": "https://tracking.example/456"},
            ],
        )

        self.assertEqual(
            order.tracking_entries,
            [
                {"number": "TRACK-123", "url": "https://tracking.example/123"},
                {"number": "TRACK-456", "url": "https://tracking.example/456"},
            ],
        )
        self.assertEqual(order.primary_tracking_url, "https://tracking.example/123")

    def test_tracking_entries_falls_back_to_legacy_fields(self):
        order = Order(
            tracking_numbers="TRACK-123\nTRACK-456",
            tracking_url="https://tracking.example/123",
            printful_tracking_data=[],
        )

        self.assertEqual(
            order.tracking_entries,
            [
                {"number": "TRACK-123", "url": "https://tracking.example/123"},
                {"number": "TRACK-456", "url": "https://tracking.example/123"},
            ],
        )
