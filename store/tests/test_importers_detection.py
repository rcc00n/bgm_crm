from decimal import Decimal

from django.test import SimpleTestCase

from store.importers import (
    _normalize_row,
    _parse_decimal,
    _pick_price,
    _pick_shopify_main_image_url,
    detect_shopify,
)


class ShopifyDetectionTests(SimpleTestCase):
    def test_detect_shopify_recognizes_ddc_headers(self):
        headers = [
            "SKU",
            "RETAIL PRICE",
            "Title",
            "Handle",
            "Body (HTML)",
            "Vendor",
            "Type",
            "Option1 Name",
            "Option1 Value",
            "Image Src",
            "Image Position",
        ]
        self.assertTrue(detect_shopify(headers))

    def test_pick_price_parses_retail_price_column(self):
        row_norm = _normalize_row({"RETAIL PRICE": "$55.00 "})
        raw = _pick_price(row_norm, "CAD")
        self.assertEqual(_parse_decimal(raw), Decimal("55.00"))

    def test_image_candidates_sorted_by_position(self):
        group = [
            _normalize_row({"Image Src": "https://example.com/pos2.jpg", "Image Position": "2"}),
            _normalize_row({"Image Src": "https://example.com/pos1.jpg", "Image Position": "1"}),
            _normalize_row({"Image Src": "https://example.com/nopos.jpg", "Image Position": ""}),
        ]
        self.assertEqual(_pick_shopify_main_image_url(group), "https://example.com/pos1.jpg")

