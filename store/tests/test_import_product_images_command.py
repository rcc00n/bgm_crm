from __future__ import annotations

import csv
import shutil
import tempfile
from collections import Counter
from decimal import Decimal
from io import StringIO
from unittest.mock import patch
from urllib.error import HTTPError

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.test.utils import override_settings

from store.models import Category, Product
from store.management.commands.import_product_images import (
    ImportStats,
    RemoteImageResolver,
    _build_csv_candidates_with_options,
    _choose_diverse_fallback_candidate,
)


def _csv_text(*rows: str) -> str:
    header = "SKU,RETAIL PRICE,Title,Handle,Image Src,Image Position"
    return "\n".join([header, *rows]) + "\n"


class _FakeHTTPResponse:
    def __init__(self, body: bytes, *, status: int = 200, content_type: str = "image/jpeg"):
        self._body = body
        self._offset = 0
        self.status = status
        self.headers = {"Content-Type": content_type}

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._body) - self._offset
        start = self._offset
        end = min(len(self._body), start + size)
        self._offset = end
        return self._body[start:end]

    def getcode(self) -> int:
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class ImportProductImagesCommandTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Default", slug="default")

    def _create_product(self, **overrides) -> Product:
        defaults = {
            "name": "Test Product",
            "slug": "test-product",
            "sku": "TEST-SKU",
            "category": self.category,
            "price": Decimal("100.00"),
            "main_image": "store/placeholders/logo1.jpg",
        }
        defaults.update(overrides)
        return Product.objects.create(**defaults)

    def test_updates_placeholder_products_by_name_match(self):
        target = self._create_product(
            name='Cat & DPF Race Pipe (2011-2019 Ford Powerstroke 6.7L)',
            slug="dieselr-cat-dpf-race-pipe-2011-2026-ford-powerstroke-67l",
            sku="SKU-TARGET",
        )
        untouched = self._create_product(
            name='Cat & DPF Race Pipe (2011-2019 Ford Powerstroke 6.7L)',
            slug="other-product",
            sku="SKU-OTHER",
            main_image="https://example.com/existing.jpg",
        )
        csv_text = _csv_text(
            "DDC-3F11,$499.00,\"2011-2018 Powerstroke 4\\\" SS Cat & DPF Delete Pipe (DDC-3F11)\","
            "2011-ford-6-7l-4-cat-dpf-delete-nb,https://cdn.example.com/powerstroke-delete.jpg,1"
        )
        out = StringIO()

        with patch("sys.stdin", StringIO(csv_text)):
            call_command(
                "import_product_images",
                "--stdin",
                "--match-by-name",
                "--only-current-image",
                "store/placeholders/logo1.jpg",
                stdout=out,
            )

        target.refresh_from_db()
        untouched.refresh_from_db()

        self.assertEqual(target.main_image.name, "https://cdn.example.com/powerstroke-delete.jpg")
        self.assertEqual(untouched.main_image.name, "https://example.com/existing.jpg")
        self.assertIn("matched_name: 1", out.getvalue())

    def test_only_current_image_filter_blocks_exact_match_updates(self):
        product = self._create_product(
            name="Exact Match Product",
            slug="exact-match-product",
            main_image="https://example.com/existing.jpg",
        )
        csv_text = _csv_text(
            "EXACT-SKU,$55.00,Exact Match Product,exact-match-product,https://cdn.example.com/exact.jpg,1"
        )

        with patch("sys.stdin", StringIO(csv_text)):
            call_command(
                "import_product_images",
                "--stdin",
                "--only-current-image",
                "store/placeholders/logo1.jpg",
            )

        product.refresh_from_db()
        self.assertEqual(product.main_image.name, "https://example.com/existing.jpg")

    def test_only_current_prefix_updates_placeholder_variants(self):
        product = self._create_product(
            name="Prefix Match Product",
            slug="prefix-match-product",
            sku="PREFIX-SKU",
            main_image="store/placeholders/logo1__копия.jpg",
        )
        csv_text = _csv_text(
            "PREFIX-SKU,$55.00,Prefix Match Product,prefix-match-product,https://cdn.example.com/prefix.jpg,1"
        )

        with patch("sys.stdin", StringIO(csv_text)):
            call_command(
                "import_product_images",
                "--stdin",
                "--only-current-prefix",
                "store/placeholders/",
            )

        product.refresh_from_db()
        self.assertEqual(product.main_image.name, "https://cdn.example.com/prefix.jpg")

    def test_skips_low_confidence_name_matches(self):
        product = self._create_product(
            name="Transmission Tune File (2023-2025 6.7L Ford Powerstroke)",
            slug="dieselr-ez-lynk-transmission-tune-file-2023-2025-67l-ford-powerstroke",
            sku="SKU-TUNE",
        )
        csv_text = _csv_text(
            "DDC-3F11,$499.00,\"2011-2018 Powerstroke 4\\\" SS Cat & DPF Delete Pipe (DDC-3F11)\","
            "2011-ford-6-7l-4-cat-dpf-delete-nb,https://cdn.example.com/powerstroke-delete.jpg,1"
        )
        out = StringIO()

        with patch("sys.stdin", StringIO(csv_text)):
            call_command(
                "import_product_images",
                "--stdin",
                "--match-by-name",
                "--only-current-image",
                "store/placeholders/logo1.jpg",
                stdout=out,
            )

        product.refresh_from_db()
        self.assertEqual(product.main_image.name, "store/placeholders/logo1.jpg")
        self.assertIn("skipped_low_confidence: 1", out.getvalue())

    def test_broad_fallback_can_fill_low_confidence_product(self):
        product = self._create_product(
            name="Transmission Tune File (2023-2025 6.7L Ford Powerstroke)",
            slug="dieselr-ez-lynk-transmission-tune-file-2023-2025-67l-ford-powerstroke",
            sku="SKU-TUNE-BROAD",
        )
        csv_text = _csv_text(
            "DDC-GAU-A025,$129.00,Universal MM3 to CTS2 Pod Improved Adapter (DDC-GAU-A025),"
            "universal-cts2-pod-to-mm3-mount,https://cdn.example.com/mm3-adapter.jpg,1"
        )
        out = StringIO()

        with patch("sys.stdin", StringIO(csv_text)):
            call_command(
                "import_product_images",
                "--stdin",
                "--match-by-name",
                "--broad-fallback",
                "--only-current-image",
                "store/placeholders/logo1.jpg",
                stdout=out,
            )

        product.refresh_from_db()
        self.assertEqual(product.main_image.name, "https://cdn.example.com/mm3-adapter.jpg")
        self.assertIn("matched_broad: 1", out.getvalue())

    def test_validate_remote_images_skips_broken_primary_and_uses_next_image(self):
        product = self._create_product(
            name="Exact Match Product",
            slug="exact-match-product",
            sku="BROKEN-FIRST-SKU",
        )
        csv_text = _csv_text(
            "BROKEN-FIRST-SKU,$55.00,Exact Match Product,exact-match-product,https://cdn.example.com/broken.jpg,1",
            "BROKEN-FIRST-SKU,$55.00,Exact Match Product,exact-match-product,https://cdn.example.com/valid.jpg,2",
        )

        def _urlopen(req, timeout=0):
            url = req.full_url
            if url.endswith("/broken.jpg"):
                raise HTTPError(url, 404, "Not Found", hdrs={"Content-Type": "text/html"}, fp=None)
            if url.endswith("/valid.jpg"):
                return _FakeHTTPResponse(b"valid-image", content_type="image/jpeg")
            raise AssertionError(f"Unexpected URL: {url}")

        with patch("store.management.commands.import_product_images.urlopen", side_effect=_urlopen):
            with patch("sys.stdin", StringIO(csv_text)):
                call_command(
                    "import_product_images",
                    "--stdin",
                    "--validate-remote-images",
                    "--only-current-prefix",
                    "store/placeholders/",
                )

        product.refresh_from_db()
        self.assertEqual(product.main_image.name, "https://cdn.example.com/valid.jpg")

    def test_include_broken_current_targets_broken_remote_products(self):
        product = self._create_product(
            name="Exact Match Product",
            slug="exact-match-product",
            sku="BROKEN-CURRENT-SKU",
            main_image="https://cdn.example.com/current-broken.jpg",
        )
        csv_text = _csv_text(
            "BROKEN-CURRENT-SKU,$55.00,Exact Match Product,exact-match-product,https://cdn.example.com/replacement.jpg,1"
        )

        def _urlopen(req, timeout=0):
            url = req.full_url
            if url.endswith("/current-broken.jpg"):
                raise HTTPError(url, 404, "Not Found", hdrs={"Content-Type": "text/html"}, fp=None)
            if url.endswith("/replacement.jpg"):
                return _FakeHTTPResponse(b"replacement-image", content_type="image/jpeg")
            raise AssertionError(f"Unexpected URL: {url}")

        with patch("store.management.commands.import_product_images.urlopen", side_effect=_urlopen):
            with patch("sys.stdin", StringIO(csv_text)):
                call_command(
                    "import_product_images",
                    "--stdin",
                    "--include-broken-current",
                    "--validate-remote-images",
                )

        product.refresh_from_db()
        self.assertEqual(product.main_image.name, "https://cdn.example.com/replacement.jpg")

    def test_download_images_saves_local_file_into_storage(self):
        product = self._create_product(
            name="Download Match Product",
            slug="download-match-product",
            sku="DOWNLOAD-SKU",
        )
        csv_text = _csv_text(
            "DOWNLOAD-SKU,$55.00,Download Match Product,download-match-product,https://cdn.example.com/download.webp,1"
        )
        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)

        def _urlopen(req, timeout=0):
            url = req.full_url
            if url.endswith("/download.webp"):
                return _FakeHTTPResponse(b"webp-image", content_type="image/webp")
            raise AssertionError(f"Unexpected URL: {url}")

        with override_settings(MEDIA_ROOT=media_root):
            with patch("store.management.commands.import_product_images.urlopen", side_effect=_urlopen):
                with patch("sys.stdin", StringIO(csv_text)):
                    call_command(
                        "import_product_images",
                        "--stdin",
                        "--validate-remote-images",
                        "--download-images",
                        "--only-current-prefix",
                        "store/placeholders/",
                    )
            product.refresh_from_db()
            self.assertTrue(product.main_image.name.startswith("store/products/imported/ddc/"))
            self.assertTrue(product.main_image.storage.exists(product.main_image.name))

        product.refresh_from_db()
        self.assertTrue(product.main_image.name.startswith("store/products/imported/ddc/"))


class ImportProductImagesHelperTests(SimpleTestCase):
    def test_candidate_build_uses_type_and_years_for_classification(self):
        csv_text = _csv_text(
            'DDC-421012,$55.00,Performance Exhaust,performance-exhaust,https://cdn.example.com/exhaust.jpg,1'
        )
        rows = list(csv_text.splitlines())
        rows[0] = rows[0] + ",Vendor,Type,Years"
        rows[1] = rows[1] + ',Dirty Diesel Customs,Downpipe Back Exhaust System,"2011-2019 Ford F-Series 6.7L Powerstroke"'
        out = "\n".join(rows) + "\n"

        candidates = _build_csv_candidates_with_options(
            csv.DictReader(StringIO(out)),
            ImportStats(),
            resolver=RemoteImageResolver(validate=False),
        )
        candidate = candidates[0]

        self.assertEqual(candidate.family, "powerstroke")
        self.assertEqual(candidate.kind, "downpipe_exhaust")

    def test_diverse_fallback_spreads_between_multiple_candidates(self):
        csv_text = (
            "SKU,RETAIL PRICE,Title,Handle,Image Src,Image Position,Vendor,Type,Years\n"
            "SW-1114,$55.00,Powerstroke Switch Alpha,powerstroke-switch-alpha,https://cdn.example.com/a.jpg,1,Dirty Diesel Customs,Switch,\"2011-2014 Ford Powerstroke 6.7L\"\n"
            "SW-1519,$55.00,Powerstroke Switch Beta,powerstroke-switch-beta,https://cdn.example.com/b.jpg,1,Dirty Diesel Customs,Switch,\"2015-2019 Ford Powerstroke 6.7L\"\n"
        )
        candidates = _build_csv_candidates_with_options(
            csv.DictReader(StringIO(csv_text)),
            ImportStats(),
            resolver=RemoteImageResolver(validate=False),
        )
        usage = Counter()
        first = Product(name="SOTF Harness (2011-2014 Powerstroke)", slug="sotf-harness-2011-2014-powerstroke")
        second = Product(name="SOTF Harness (2015-2019 Powerstroke)", slug="sotf-harness-2015-2019-powerstroke")

        first_candidate, _ = _choose_diverse_fallback_candidate(first, candidates, image_usage=usage)
        self.assertIsNotNone(first_candidate)
        usage[first_candidate.image_url] += 1

        second_candidate, _ = _choose_diverse_fallback_candidate(second, candidates, image_usage=usage)
        self.assertIsNotNone(second_candidate)
        self.assertNotEqual(first_candidate.image_url, second_candidate.image_url)
