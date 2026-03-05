from __future__ import annotations

import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from core.services.printful import create_printful_order, find_printful_order_by_external_id, quote_printful_shipping_rates


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.status = status
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, *_args, **_kwargs):
        return self._payload


@override_settings(
    PRINTFUL_TOKEN="token-123",
    PRINTFUL_STORE_ID="12177083",
    PRINTFUL_MERCH_CACHE_SECONDS=0,
)
class PrintfulCheckoutApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_quote_printful_shipping_rates_normalizes_response(self):
        def _urlopen(req, timeout=0):
            self.assertEqual(req.full_url, "https://api.printful.com/shipping/rates")
            payload = json.loads(req.data.decode("utf-8"))
            self.assertEqual(payload["items"][0]["variant_id"], 18730)
            return _FakeResponse(
                {
                    "code": 200,
                    "result": [
                        {
                            "id": "PRINTFUL_MEDIUM_DDP",
                            "name": "Standard DDP",
                            "rate": "25.49",
                            "currency": "CAD",
                            "minDeliveryDate": "2026-03-14",
                            "maxDeliveryDate": "2026-03-17",
                        },
                        {
                            "id": "STANDARD",
                            "name": "Flat Rate",
                            "rate": "11.95",
                            "currency": "CAD",
                            "minDeliveryDate": "2026-03-13",
                            "maxDeliveryDate": "2026-03-16",
                        },
                    ],
                }
            )

        with patch("core.services.printful.urlopen", side_effect=_urlopen):
            rates = quote_printful_shipping_rates(
                recipient={
                    "name": "Test User",
                    "address1": "123 Main St",
                    "city": "Medicine Hat",
                    "state_code": "AB",
                    "country_code": "CA",
                    "zip": "T1A 0A1",
                },
                items=[{"variant_id": 18730, "quantity": 1}],
                currency="CAD",
            )

        self.assertEqual([row["id"] for row in rates], ["STANDARD", "PRINTFUL_MEDIUM_DDP"])
        self.assertEqual(rates[0]["rate"], "11.95")
        self.assertEqual(rates[0]["min_delivery_date"], "2026-03-13")

    def test_create_printful_order_uses_confirm_query(self):
        def _urlopen(req, timeout=0):
            self.assertEqual(req.full_url, "https://api.printful.com/orders?confirm=1")
            payload = json.loads(req.data.decode("utf-8"))
            self.assertEqual(payload["shipping"], "STANDARD")
            self.assertEqual(payload["external_id"], "bgm-order-123")
            self.assertEqual(payload["items"][0]["sync_variant_id"], 4346110931)
            return _FakeResponse(
                {
                    "code": 200,
                    "result": {
                        "id": 148615541,
                        "status": "pending",
                        "shipping": "STANDARD",
                        "shipping_service_name": "Flat Rate",
                    },
                }
            )

        with patch("core.services.printful.urlopen", side_effect=_urlopen):
            payload = create_printful_order(
                recipient={
                    "name": "Test User",
                    "address1": "123 Main St",
                    "city": "Medicine Hat",
                    "state_code": "AB",
                    "country_code": "CA",
                    "zip": "T1A 0A1",
                },
                items=[{"sync_variant_id": 4346110931, "quantity": 1}],
                shipping="STANDARD",
                external_id="bgm-order-123",
                confirm=True,
            )

        self.assertEqual(payload["id"], 148615541)
        self.assertEqual(payload["shipping"], "STANDARD")

    def test_find_printful_order_by_external_id_scans_order_pages(self):
        responses = [
            _FakeResponse(
                {
                    "code": 200,
                    "result": [
                        {"id": 101, "external_id": "bgm-order-1"},
                    ],
                    "paging": {"total": 2, "limit": 1, "offset": 0},
                }
            ),
            _FakeResponse(
                {
                    "code": 200,
                    "result": [
                        {"id": 202, "external_id": "bgm-order-202"},
                    ],
                    "paging": {"total": 2, "limit": 1, "offset": 1},
                }
            ),
        ]

        def _urlopen(req, timeout=0):
            self.assertTrue(req.full_url.startswith("https://api.printful.com/orders?"))
            return responses.pop(0)

        with patch("core.services.printful.urlopen", side_effect=_urlopen):
            payload = find_printful_order_by_external_id("bgm-order-202", page_size=1, max_pages=2)

        self.assertEqual(payload["id"], 202)
