from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class SyncPrintfulMerchCatalogCommandTests(SimpleTestCase):
    @patch("store.management.commands.sync_printful_merch_catalog._sync_printful_merch_products")
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

    @patch("store.management.commands.sync_printful_merch_catalog.get_printful_merch_feed")
    def test_raises_when_printful_returns_no_products(self, get_printful_merch_feed):
        get_printful_merch_feed.return_value = {"products": [], "error": "api_error"}

        with self.assertRaises(CommandError):
            call_command("sync_printful_merch_catalog")
