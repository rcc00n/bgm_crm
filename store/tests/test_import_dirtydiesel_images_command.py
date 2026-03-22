from __future__ import annotations

import shutil
import tempfile
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.test.utils import override_settings

from store.dirtydiesel_import.types import SourceProduct
from store.models import Category, Product


class _FakeHTTPResponse:
    def __init__(self, body: bytes, *, content_type: str = "image/jpeg"):
        self._body = body
        self._offset = 0
        self.headers = {"Content-Type": content_type}

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._body) - self._offset
        start = self._offset
        end = min(len(self._body), start + size)
        self._offset = end
        return self._body[start:end]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class ImportDirtyDieselImagesCommandTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(
            name="Electronics",
            slug="electronics-electronics-accessories-cables",
            image="store/categories/electronics.png",
        )
        self.product = Product.objects.create(
            name="OBD-II Splitter Unlock Cable (2018+ 6.7L Cummins)",
            slug="obdii-splitter-unlock-cable-2018-cummins",
            sku="341-03000",
            category=self.category,
            is_in_house=False,
            price=Decimal("39.99"),
            main_image="store/products/old.png",
        )
        self.source_product = SourceProduct(
            product_id=100,
            variant_id=200,
            sku="341-03000",
            product_name="2018+ Cummins OBDII Splitter Unlock Cable (341-03000)",
            variant_name="Default Title",
            supplier_name="GDP",
            supplier_category="OBDII Splitter",
            product_page_url="https://www.dirtydieselcustom.ca/products/2018-cummins-obdii-splitter-unlock-cable-gdp68000u",
            image_urls=(
                "https://cdn.example.com/ddc/341-03000-main.webp",
                "https://cdn.example.com/ddc/341-03000-gallery.webp",
            ),
        )

    def _fake_urlopen(self, req, timeout=0):
        url = req.full_url
        if url.endswith("341-03000-main.webp"):
            return _FakeHTTPResponse(b"main-image", content_type="image/webp")
        if url.endswith("341-03000-gallery.webp"):
            return _FakeHTTPResponse(b"gallery-image", content_type="image/webp")
        raise AssertionError(f"Unexpected URL requested: {url}")

    def test_apply_updates_exact_sku_match(self):
        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
        output = StringIO()

        with override_settings(MEDIA_ROOT=media_root):
            with patch(
                "store.dirtydiesel_import.source.DirtyDieselCatalogClient.fetch_catalog",
                return_value=[self.source_product],
            ):
                with patch("store.fassride_import.images.urlopen", side_effect=self._fake_urlopen):
                    call_command(
                        "import_dirtydiesel_images",
                        "--apply",
                        stdout=output,
                    )

        self.product.refresh_from_db()

        self.assertTrue(self.product.main_image.name.startswith("store/imports/dirtydiesel/assets/"))
        self.assertEqual(self.product.images.count(), 1)
        self.assertIn("updated_products=1", output.getvalue())

    def test_in_house_products_are_ignored(self):
        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
        output = StringIO()
        self.product.is_in_house = True
        self.product.save(update_fields=["is_in_house"])

        with override_settings(MEDIA_ROOT=media_root):
            with patch(
                "store.dirtydiesel_import.source.DirtyDieselCatalogClient.fetch_catalog",
                return_value=[self.source_product],
            ):
                with patch("store.fassride_import.images.urlopen", side_effect=self._fake_urlopen):
                    call_command(
                        "import_dirtydiesel_images",
                        "--apply",
                        stdout=output,
                    )

        self.product.refresh_from_db()

        self.assertEqual(self.product.main_image.name, "store/products/old.png")
        self.assertIn("updated_products=0", output.getvalue())

    def test_fass_categories_are_excluded_by_default(self):
        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
        output = StringIO()
        fass_category = Category.objects.create(
            name="FASS Accessories",
            slug="fass-accessories",
            image="store/categories/fassfuel_-_fuel_system_upgrade.png",
        )
        product = Product.objects.create(
            name="Some FASS Re-sold Product",
            slug="some-fass-re-sold-product",
            sku="341-03000",
            category=fass_category,
            is_in_house=False,
            price=Decimal("39.99"),
            main_image="store/products/fass-old.png",
        )

        with override_settings(MEDIA_ROOT=media_root):
            with patch(
                "store.dirtydiesel_import.source.DirtyDieselCatalogClient.fetch_catalog",
                return_value=[self.source_product],
            ):
                with patch("store.fassride_import.images.urlopen", side_effect=self._fake_urlopen):
                    call_command(
                        "import_dirtydiesel_images",
                        "--apply",
                        stdout=output,
                    )

        product.refresh_from_db()

        self.assertEqual(product.main_image.name, "store/products/fass-old.png")
        self.assertIn("updated_products=1", output.getvalue())
