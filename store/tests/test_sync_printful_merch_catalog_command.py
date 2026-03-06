from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class SyncPrintfulMerchCatalogCommandTests(SimpleTestCase):
    @patch("store.management.commands.sync_printful_merch_catalog.sync_printful_merch_products")
    @patch("store.management.commands.sync_printful_merch_catalog.get_printful_merch_feed")
    def test_syncs_products_from_printful_feed(self, get_printful_merch_feed, sync_printful_merch_products):
        get_printful_merch_feed.return_value = {
            "products": [{"id": 101, "name": "Test Tee", "variants": []}],
            "error": "",
        }
        out = StringIO()

        call_command("sync_printful_merch_catalog", stdout=out)

        sync_printful_merch_products.assert_called_once_with([{"id": 101, "name": "Test Tee", "variants": []}])
        self.assertIn("Synced 1 Printful merch products.", out.getvalue())

    @patch("store.management.commands.sync_printful_merch_catalog.sync_printful_merch_products")
    @patch("store.management.commands.sync_printful_merch_catalog.get_printful_merch_product")
    def test_syncs_specific_product_ids(self, get_printful_merch_product, sync_printful_merch_products):
        get_printful_merch_product.side_effect = [
            {"id": 101, "name": "Test Tee", "variants": []},
            {"id": 202, "name": "Test Hat", "variants": []},
        ]
        out = StringIO()

        call_command("sync_printful_merch_catalog", "--product-id", "101", "--product-id", "202", stdout=out)

        self.assertEqual(get_printful_merch_product.call_count, 2)
        sync_printful_merch_products.assert_called_once_with(
            [
                {"id": 101, "name": "Test Tee", "variants": []},
                {"id": 202, "name": "Test Hat", "variants": []},
            ]
        )
        self.assertIn("Synced 2 Printful merch products.", out.getvalue())

    @patch("store.management.commands.sync_printful_merch_catalog.get_printful_merch_feed")
    def test_raises_when_printful_returns_no_products(self, get_printful_merch_feed):
        get_printful_merch_feed.return_value = {"products": [], "error": "api_error"}

        with self.assertRaises(CommandError):
            call_command("sync_printful_merch_catalog")

    @patch("store.management.commands.sync_printful_merch_catalog.get_printful_merch_product")
    def test_raises_when_specific_product_sync_returns_nothing(self, get_printful_merch_product):
        get_printful_merch_product.return_value = {}

        with self.assertRaises(CommandError):
            call_command("sync_printful_merch_catalog", "--product-id", "101")
