from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from store.importers import import_products
from store.models import Category, Product


def _ddc_csv_bytes(*, handle: str, title: str, image_url_pos1: str, image_url_pos2: str) -> bytes:
    # DDC "Shopify-like" CSV: SKU + RETAIL PRICE, plus Image Src / Image Position.
    rows = [
        "SKU,RETAIL PRICE,Title,Handle,Image Src,Image Position,Option1 Name,Option1 Value",
        f"DDC-SKU-1,$55.00,{title},{handle},{image_url_pos2},2,Size,S",
        f",,,{handle},{image_url_pos1},1,,",
    ]
    return ("\n".join(rows) + "\n").encode("utf-8")


class ShopifyImageImportTests(TestCase):
    def test_ddc_import_creates_one_product_per_handle_and_sets_main_image(self):
        cat = Category.objects.create(name="Default", slug="default")

        handle = "test-handle"
        img1 = "https://cdn.shopify.com/s/files/1/2084/8209/products/" + ("a" * 150) + ".jpg?v=1"
        img2 = "https://cdn.shopify.com/s/files/1/2084/8209/products/" + ("b" * 150) + ".jpg?v=2"

        uploaded = SimpleUploadedFile(
            "ddc.csv",
            _ddc_csv_bytes(handle=handle, title="Test Product", image_url_pos1=img1, image_url_pos2=img2),
            content_type="text/csv",
        )

        result = import_products(
            uploaded_file=uploaded,
            mode="auto",
            default_category=cat,
            default_currency="CAD",
            update_existing=False,
            create_missing_categories=True,
            dry_run=False,
        )

        self.assertEqual(result.created_products, 1)
        self.assertEqual(Product.objects.count(), 1)

        product = Product.objects.get(slug=handle)
        self.assertEqual(product.main_image.name, img1)

        # One variant row yields one option; image-only rows do not create products/options.
        self.assertEqual(result.created_options, 1)

    def test_ddc_import_updates_existing_by_slug_and_overwrites_main_image_without_wiping_tags(self):
        cat = Category.objects.create(name="Default", slug="default")
        handle = "test-handle"

        existing = Product.objects.create(
            name="Existing",
            slug=handle,
            sku="EXIST-SKU",
            category=cat,
            price=Decimal("10.00"),
            tags=["keep"],
            main_image="https://example.com/old.jpg",
        )

        new_img = "https://cdn.shopify.com/s/files/1/2084/8209/products/" + ("c" * 150) + ".jpg?v=3"
        uploaded = SimpleUploadedFile(
            "ddc.csv",
            _ddc_csv_bytes(handle=handle, title="Updated Title", image_url_pos1=new_img, image_url_pos2=new_img),
            content_type="text/csv",
        )

        result = import_products(
            uploaded_file=uploaded,
            mode="auto",
            default_category=None,  # category omitted from CSV; should not block updates
            default_currency="CAD",
            update_existing=True,
            create_missing_categories=True,
            dry_run=False,
        )

        self.assertEqual(result.updated_products, 1)
        self.assertEqual(Product.objects.count(), 1)

        existing.refresh_from_db()
        self.assertEqual(existing.tags, ["keep"])
        self.assertEqual(existing.main_image.name, new_img)

    def test_ddc_import_does_not_create_duplicate_when_update_existing_is_off(self):
        cat = Category.objects.create(name="Default", slug="default")
        handle = "test-handle"
        Product.objects.create(
            name="Existing",
            slug=handle,
            sku="EXIST-SKU",
            category=cat,
            price=Decimal("10.00"),
        )

        img = "https://cdn.shopify.com/s/files/1/2084/8209/products/" + ("d" * 150) + ".jpg?v=4"
        uploaded = SimpleUploadedFile(
            "ddc.csv",
            _ddc_csv_bytes(handle=handle, title="Test Product", image_url_pos1=img, image_url_pos2=img),
            content_type="text/csv",
        )

        result = import_products(
            uploaded_file=uploaded,
            mode="auto",
            default_category=None,
            default_currency="CAD",
            update_existing=False,
            create_missing_categories=True,
            dry_run=False,
        )

        self.assertEqual(result.skipped_products, 1)
        self.assertEqual(Product.objects.count(), 1)

