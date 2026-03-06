from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from accounts.views import _get_merch_listing_products


@override_settings(PRINTFUL_MERCH_CATALOG_URL="https://printful.example/catalog")
class MerchListingSourceTests(SimpleTestCase):
    @patch("accounts.views.get_printful_merch_feed")
    @patch("accounts.views._build_store_merch_products")
    def test_prefers_local_store_merch_products(self, build_store_merch_products, get_printful_merch_feed):
        build_store_merch_products.return_value = [{"id": 1, "name": "Local Tee"}]

        products, catalog_url, error = _get_merch_listing_products()

        self.assertEqual(products, [{"id": 1, "name": "Local Tee"}])
        self.assertEqual(catalog_url, "https://printful.example/catalog")
        self.assertEqual(error, "")
        get_printful_merch_feed.assert_not_called()

    @patch("accounts.views._enrich_printful_merch_products")
    @patch("accounts.views.get_printful_merch_feed")
    @patch("accounts.views._build_store_merch_products")
    def test_falls_back_to_printful_feed_when_store_is_empty(
        self,
        build_store_merch_products,
        get_printful_merch_feed,
        enrich_printful_merch_products,
    ):
        build_store_merch_products.return_value = []
        get_printful_merch_feed.return_value = {
            "products": [{"id": 2, "name": "Feed Tee"}],
            "catalog_url": "https://printful.example/live",
            "error": "",
        }
        enrich_printful_merch_products.return_value = [{"id": 2, "name": "Feed Tee"}]

        products, catalog_url, error = _get_merch_listing_products()

        self.assertEqual(products, [{"id": 2, "name": "Feed Tee"}])
        self.assertEqual(catalog_url, "https://printful.example/live")
        self.assertEqual(error, "")
        get_printful_merch_feed.assert_called_once()
        enrich_printful_merch_products.assert_called_once_with([{"id": 2, "name": "Feed Tee"}])
