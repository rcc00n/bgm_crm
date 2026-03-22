from __future__ import annotations

import shutil
import tempfile
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.test.utils import override_settings

from store.fassride_import.types import CuratedCategoryImage, SourceProduct
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


class ImportFassrideImagesCommandTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(
            name="FASS Filters",
            slug="fass-filters",
            image="store/categories/fassfuel_-_fuel_system_upgrade.png",
        )
        self.product = Product.objects.create(
            name="FASS Signature Series / Titanium (Extreme Water Separator)",
            slug="fass-signature-series-titanium-extreme-water-separator",
            sku="XWS3002",
            category=self.category,
            price=Decimal("39.99"),
            main_image="store/categories/fassfuel_-_fuel_system_upgrade.png",
        )
        self.source_product = SourceProduct(
            product_id=1234,
            part_number="XWS3002",
            supplier_name="FASS Diesel Fuel Systems",
            supplier_category="Replacement Filters",
            name="FASS Fuel Filter XWS3002",
            medium_description="Water separator",
            long_description="Long description",
            product_page_url="https://www.fassride.com/details?id=1234",
            image_urls=(
                "https://cdn.example.com/fass/xws3002-main.jpg",
                "https://cdn.example.com/fass/xws3002-gallery.jpg",
            ),
        )

    def _fake_urlopen(self, req, timeout=0):
        url = req.full_url
        if url.endswith("xws3002-main.jpg"):
            return _FakeHTTPResponse(b"main-image", content_type="image/jpeg")
        if url.endswith("xws3002-gallery.jpg"):
            return _FakeHTTPResponse(b"gallery-image", content_type="image/jpeg")
        raise AssertionError(f"Unexpected URL requested: {url}")

    def test_apply_updates_generic_product_and_category_images(self):
        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
        output = StringIO()

        with override_settings(MEDIA_ROOT=media_root):
            with patch(
                "store.fassride_import.source.FassrideApiClient.fetch_catalog",
                return_value=[self.source_product],
            ):
                with patch("store.fassride_import.images.urlopen", side_effect=self._fake_urlopen):
                    call_command(
                        "import_fassride_images",
                        "--apply",
                        "--category-slug",
                        "fass-filters",
                        stdout=output,
                    )

        self.product.refresh_from_db()
        self.category.refresh_from_db()

        self.assertTrue(self.product.main_image.name.startswith("store/imports/fassride/assets/"))
        self.assertLessEqual(len(self.product.main_image.name), 100)
        self.assertEqual(self.category.image.name, self.product.main_image.name)
        gallery_images = list(self.product.images.order_by("sort_order").values_list("image", flat=True))
        self.assertEqual(len(gallery_images), 1)
        self.assertTrue(gallery_images[0].startswith("store/imports/fassride/assets/"))
        self.assertIn("updated_products=1", output.getvalue())
        self.assertIn("updated_categories=1", output.getvalue())

    def test_rerun_is_idempotent_and_does_not_duplicate_gallery(self):
        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)

        with override_settings(MEDIA_ROOT=media_root):
            with patch(
                "store.fassride_import.source.FassrideApiClient.fetch_catalog",
                return_value=[self.source_product],
            ):
                with patch("store.fassride_import.images.urlopen", side_effect=self._fake_urlopen):
                    call_command(
                        "import_fassride_images",
                        "--apply",
                        "--category-slug",
                        "fass-filters",
                    )
                    call_command(
                        "import_fassride_images",
                        "--apply",
                        "--category-slug",
                        "fass-filters",
                    )

        self.product.refresh_from_db()
        self.assertEqual(self.product.images.count(), 1)

    def test_curated_category_cover_replaces_prior_imported_category_cover(self):
        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
        output = StringIO()
        category = Category.objects.create(
            name="FASS Fuel Systems",
            slug="fass-fuel-systems",
            image="store/imports/fassride/assets/old-category-cover.png",
        )
        curated_cover = CuratedCategoryImage(
            category_slug="fass-fuel-systems",
            source_page_url="https://www.fassride.com/fuel-air-separation-system",
            image_url="https://cdn.example.com/fass/fuel-systems-cover.webp",
            label="Fuel-Air Separation / Universal",
        )

        def fake_urlopen(req, timeout=0):
            url = req.full_url
            if url.endswith("fuel-systems-cover.webp"):
                return _FakeHTTPResponse(b"fuel-systems-cover", content_type="image/webp")
            raise AssertionError(f"Unexpected URL requested: {url}")

        with override_settings(MEDIA_ROOT=media_root):
            with patch(
                "store.fassride_import.source.FassrideApiClient.fetch_catalog",
                return_value=[],
            ):
                with patch(
                    "store.fassride_import.source.FassrideApiClient.fetch_curated_category_covers",
                    return_value={"fass-fuel-systems": curated_cover},
                ):
                    with patch("store.fassride_import.images.urlopen", side_effect=fake_urlopen):
                        call_command(
                            "import_fassride_images",
                            "--apply",
                            "--category-slug",
                            "fass-fuel-systems",
                            stdout=output,
                        )

        category.refresh_from_db()

        self.assertTrue(category.image.name.startswith("store/imports/fassride/assets/"))
        self.assertLessEqual(len(category.image.name), 100)
        self.assertNotEqual(category.image.name, "store/imports/fassride/assets/old-category-cover.png")
        self.assertIn("updated_products=0", output.getvalue())
        self.assertIn("updated_categories=1", output.getvalue())
