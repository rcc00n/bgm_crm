from __future__ import annotations

import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from core.services.printful import get_printful_merch_feed


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


class PrintfulMerchFeedTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @override_settings(PRINTFUL_TOKEN="")
    def test_disabled_when_token_missing(self):
        with patch("core.services.printful.urlopen") as mocked_urlopen:
            feed = get_printful_merch_feed(force_refresh=True)

        self.assertFalse(feed["enabled"])
        self.assertEqual(feed["products"], [])
        mocked_urlopen.assert_not_called()

    @override_settings(
        PRINTFUL_TOKEN="token-123",
        PRINTFUL_MERCH_CATALOG_URL="https://shop.example.com/merch",
        PRINTFUL_MERCH_SHOW_PRICE=True,
        PRINTFUL_MERCH_LIMIT=8,
        PRINTFUL_MERCH_CACHE_SECONDS=0,
        PRINTFUL_TIMEOUT_SECONDS=1,
    )
    def test_builds_products_with_price_from_sync_product_details(self):
        def _urlopen(req, timeout=0):
            if req.full_url.endswith("/sync/products?limit=8&offset=0"):
                return _FakeResponse(
                    {
                        "code": 200,
                        "result": [
                            {
                                "id": 101,
                                "name": "BGM Tee",
                                "thumbnail_url": "https://cdn.example.com/tee.jpg",
                                "external_id": "",
                                "variants": 3,
                            }
                        ],
                    }
                )
            if req.full_url.endswith("/sync/products/101"):
                return _FakeResponse(
                    {
                        "code": 200,
                        "result": {
                            "sync_variants": [
                                {"retail_price": "29.99"},
                                {"retail_price": "34.99"},
                            ]
                        },
                    }
                )
            raise AssertionError(f"Unexpected URL: {req.full_url}")

        with patch("core.services.printful.urlopen", side_effect=_urlopen):
            feed = get_printful_merch_feed(force_refresh=True)

        self.assertTrue(feed["enabled"])
        self.assertEqual(feed["error"], "")
        self.assertEqual(len(feed["products"]), 1)

        product = feed["products"][0]
        self.assertEqual(product["id"], 101)
        self.assertEqual(product["name"], "BGM Tee")
        self.assertEqual(product["image_url"], "https://cdn.example.com/tee.jpg")
        self.assertEqual(product["price_label"], "From $29.99")
        self.assertEqual(product["variant_label"], "3 variants")
        self.assertEqual(product["url"], "https://shop.example.com/merch")

    @override_settings(
        PRINTFUL_TOKEN="token-123",
        PRINTFUL_MERCH_PRODUCT_URL_TEMPLATE="https://shop.example.com/products/{slug}?p={product_id}&ext={external_id}",
        PRINTFUL_MERCH_SHOW_PRICE=False,
        PRINTFUL_MERCH_LIMIT=8,
        PRINTFUL_MERCH_CACHE_SECONDS=0,
    )
    def test_prefers_external_url_or_template_when_available(self):
        with patch(
            "core.services.printful.urlopen",
            return_value=_FakeResponse(
                {
                    "code": 200,
                    "result": [
                        {
                            "id": 1,
                            "name": "Direct Product",
                            "external_id": "https://store.example.com/direct",
                            "thumbnail_url": "",
                            "variants": 1,
                        },
                        {
                            "id": 2,
                            "name": "BGM Hoodie Black",
                            "external_id": "hoodie-black",
                            "thumbnail_url": "",
                            "variants": 2,
                        },
                    ],
                }
            ),
        ):
            feed = get_printful_merch_feed(force_refresh=True)

        self.assertEqual(len(feed["products"]), 2)
        self.assertEqual(feed["products"][0]["url"], "https://store.example.com/direct")
        self.assertEqual(
            feed["products"][1]["url"],
            "https://shop.example.com/products/bgm-hoodie-black?p=2&ext=hoodie-black",
        )

    @override_settings(
        PRINTFUL_TOKEN="token-123",
        PRINTFUL_MERCH_LIMIT=8,
        PRINTFUL_MERCH_CACHE_SECONDS=300,
        PRINTFUL_MERCH_SHOW_PRICE=False,
    )
    def test_cold_start_disk_snapshot_does_not_block_live_refresh(self):
        stale_disk_payload = {
            "enabled": True,
            "catalog_url": "",
            "products": [{"id": 999, "name": "Stale snapshot"}],
            "error": "",
        }

        with (
            patch("core.services.printful._read_last_good_payload", return_value=stale_disk_payload),
            patch(
                "core.services.printful.urlopen",
                return_value=_FakeResponse(
                    {
                        "code": 200,
                        "result": [
                            {
                                "id": 11,
                                "name": "Fresh Product",
                                "thumbnail_url": "",
                                "variants": 1,
                            }
                        ],
                    }
                ),
            ) as mocked_urlopen,
        ):
            feed = get_printful_merch_feed(force_refresh=False)

        self.assertEqual([row["id"] for row in feed["products"]], [11])
        mocked_urlopen.assert_called()
