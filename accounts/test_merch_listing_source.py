from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from accounts.views import _build_merch_listing_media, _get_merch_listing_products, _normalize_merch_image_url


@override_settings(PRINTFUL_MERCH_CATALOG_URL="https://printful.example/catalog")
class MerchListingSourceTests(SimpleTestCase):
    def test_normalize_merch_image_url_repairs_media_prefixed_remote_urls(self):
        raw = "/media/https%3A/static.wixstatic.com/media/example.jpg/v1/fit/w_2000,h_2000,q_90/file.jpg"

        normalized = _normalize_merch_image_url(raw, preset="card")

        self.assertEqual(
            normalized,
            "https://static.wixstatic.com/media/example.jpg/v1/fit/w_960,h_960,q_80/file.jpg",
        )

    def test_build_merch_listing_media_uses_normalized_card_images(self):
        carousel_images, color_swatches = _build_merch_listing_media(
            {
                "image_url": "/media/https%3A/static.wixstatic.com/media/example.jpg/v1/fit/w_2000,h_2000,q_90/file.jpg",
                "variants": [],
            }
        )

        self.assertEqual(
            carousel_images,
            ["https://static.wixstatic.com/media/example.jpg/v1/fit/w_960,h_960,q_80/file.jpg"],
        )
        self.assertEqual(color_swatches, [])

    @patch("accounts.views._enrich_printful_merch_products")
    @patch("accounts.views.get_printful_merch_feed")
    @patch("accounts.views._build_store_merch_products")
    def test_prefers_printful_feed_when_available(
        self,
        build_store_merch_products,
        get_printful_merch_feed,
        enrich_printful_merch_products,
    ):
        build_store_merch_products.return_value = [{"id": 1, "name": "Local Tee"}]
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

    @patch("accounts.views.get_printful_merch_feed")
    @patch("accounts.views._build_store_merch_products")
    def test_falls_back_to_store_merch_products_when_printful_feed_is_empty(
        self,
        build_store_merch_products,
        get_printful_merch_feed,
    ):
        build_store_merch_products.return_value = [{"id": 1, "name": "Local Tee"}]
        get_printful_merch_feed.return_value = {
            "products": [],
            "catalog_url": "https://printful.example/live",
            "error": "api_error",
        }

        products, catalog_url, error = _get_merch_listing_products()

        self.assertEqual(products, [{"id": 1, "name": "Local Tee"}])
        self.assertEqual(catalog_url, "https://printful.example/catalog")
        self.assertEqual(error, "api_error")
        get_printful_merch_feed.assert_called_once()
