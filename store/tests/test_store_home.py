from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import PageSection, StorePageCopy
from store.models import Category, Product


class StoreHomeViewTests(TestCase):
    def setUp(self):
        self.store_url = reverse("store:store")
        self.search_url = reverse("store:product-search")
        self.parts_category = Category.objects.create(name="Suspension", slug="suspension")
        self.merch_category = Category.objects.create(name="Merch", slug="merch")

    def _create_product(self, *, name: str, slug: str, sku: str, category: Category) -> Product:
        return Product.objects.create(
            name=name,
            slug=slug,
            sku=sku,
            category=category,
            price=Decimal("10.00"),
            is_active=True,
        )

    def test_store_home_excludes_merch_products_and_categories(self):
        self._create_product(
            name="Lift Kit",
            slug="lift-kit",
            sku="BGM-LIFT-1",
            category=self.parts_category,
        )
        self._create_product(
            name="BGM Hoodie",
            slug="merch-hoodie",
            sku="PF-HOODIE-1",
            category=self.merch_category,
        )

        response = self.client.get(self.store_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lift Kit")
        self.assertNotContains(response, "BGM Hoodie")
        category_slugs = list(response.context["categories"].values_list("slug", flat=True))
        self.assertEqual(category_slugs, ["suspension"])
        filter_categories = list(
            response.context["filter_form"].fields["category"].queryset.values_list("slug", flat=True)
        )
        self.assertEqual(filter_categories, ["suspension"])

    def test_filtered_results_paginate_by_50(self):
        for index in range(51):
            self._create_product(
                name=f"Shock {index:02d}",
                slug=f"shock-{index:02d}",
                sku=f"BGM-SHOCK-{index:02d}",
                category=self.parts_category,
            )

        first_page = self.client.get(self.store_url, {"q": "Shock"})

        self.assertEqual(first_page.status_code, 200)
        self.assertTrue(first_page.context["filters_active"])
        self.assertEqual(first_page.context["page_obj"].paginator.per_page, 50)
        self.assertEqual(first_page.context["page_obj"].number, 1)
        self.assertEqual(len(first_page.context["products"]), 50)
        self.assertContains(first_page, "Showing 1-50 of 51")

        second_page = self.client.get(self.store_url, {"q": "Shock", "page": 2})

        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(second_page.context["page_obj"].number, 2)
        self.assertEqual(len(second_page.context["products"]), 1)
        self.assertContains(second_page, "Showing 51-51 of 51")

    def test_product_search_excludes_merch(self):
        self._create_product(
            name="BGM Leveling Kit",
            slug="leveling-kit",
            sku="BGM-LEVEL-1",
            category=self.parts_category,
        )
        self._create_product(
            name="BGM Tee",
            slug="merch-tee",
            sku="PF-TEE-1",
            category=self.merch_category,
        )

        response = self.client.get(self.search_url, {"q": "BGM"})

        self.assertEqual(response.status_code, 200)
        names = [item["name"] for item in response.json()["results"]]
        self.assertEqual(names, ["BGM Leveling Kit"])

    def test_store_home_showcase_prioritizes_inhouse_and_excludes_duplicate_or_generic_images(self):
        inhouse = self._create_product(
            name="BGM Toolbox",
            slug="bgm-toolbox",
            sku="BGM-BOX-1",
            category=self.parts_category,
        )
        inhouse.is_in_house = True
        inhouse.main_image = "store/products/inhouse-toolbox.jpg"
        inhouse.save(update_fields=["is_in_house", "main_image"])

        unique_supplier = self._create_product(
            name="Steering Stabilizer",
            slug="steering-stabilizer",
            sku="SUP-STEER-1",
            category=self.parts_category,
        )
        unique_supplier.main_image = "store/imports/dieselr/assets/steering-stabilizer.jpg"
        unique_supplier.save(update_fields=["main_image"])

        duplicate_a = self._create_product(
            name="Duplicate Image A",
            slug="duplicate-image-a",
            sku="SUP-DUP-A",
            category=self.parts_category,
        )
        duplicate_a.main_image = "store/imports/dieselr/assets/shared-image.jpg"
        duplicate_a.save(update_fields=["main_image"])

        duplicate_b = self._create_product(
            name="Duplicate Image B",
            slug="duplicate-image-b",
            sku="SUP-DUP-B",
            category=self.parts_category,
        )
        duplicate_b.main_image = "store/imports/dieselr/assets/shared-image.jpg"
        duplicate_b.save(update_fields=["main_image"])

        generic = self._create_product(
            name="Generic Category Image Product",
            slug="generic-category-image-product",
            sku="SUP-GENERIC-1",
            category=self.parts_category,
        )
        generic.main_image = "store/categories/suspension.png"
        generic.save(update_fields=["main_image"])

        response = self.client.get(self.store_url)

        showcase_slugs = [product.slug for product in response.context["showcase_products"]]
        self.assertEqual(showcase_slugs[:2], ["bgm-toolbox", "steering-stabilizer"])
        self.assertNotIn("duplicate-image-a", showcase_slugs)
        self.assertNotIn("duplicate-image-b", showcase_slugs)
        self.assertNotIn("generic-category-image-product", showcase_slugs)

    def test_store_home_showcase_interleaves_categories(self):
        other_category = Category.objects.create(name="Drivetrain", slug="drivetrain")
        base_time = timezone.now()
        ordered_products = []
        for index, (category, suffix) in enumerate(
            (
                (self.parts_category, "a1"),
                (self.parts_category, "a2"),
                (other_category, "b1"),
                (other_category, "b2"),
            ),
            start=1,
        ):
            product = self._create_product(
                name=f"Showcase {suffix.upper()}",
                slug=f"showcase-{suffix}",
                sku=f"SHOWCASE-{suffix.upper()}",
                category=category,
            )
            product.main_image = f"store/imports/dieselr/assets/showcase-{suffix}.jpg"
            product.save(update_fields=["main_image"])
            Product.objects.filter(pk=product.pk).update(created_at=base_time.replace(microsecond=0) - timedelta(minutes=index))
            ordered_products.append(product.slug)

        response = self.client.get(self.store_url)

        showcase_slugs = [product.slug for product in response.context["showcase_products"]]
        self.assertEqual(showcase_slugs[:4], ["showcase-a1", "showcase-b1", "showcase-a2", "showcase-b2"])

    def test_store_home_showcase_limits_to_100_products(self):
        other_category = Category.objects.create(name="Exhaust", slug="exhaust")
        for index in range(105):
            category = self.parts_category if index % 2 == 0 else other_category
            product = self._create_product(
                name=f"Featured {index:03d}",
                slug=f"featured-{index:03d}",
                sku=f"FEATURED-{index:03d}",
                category=category,
            )
            product.main_image = f"store/imports/dieselr/assets/featured-{index:03d}.jpg"
            product.save(update_fields=["main_image"])

        response = self.client.get(self.store_url)

        self.assertEqual(len(response.context["showcase_products"]), 100)


class StoreHomePageSectionRenderingTests(TestCase):
    def setUp(self):
        self.store_url = reverse("store:store")
        self.store_copy = StorePageCopy.get_solo()
        self.store_copy.hero_title = "__default_store_title__"
        self.store_copy.hero_lead = "__default_store_lead__"
        self.store_copy.save(update_fields=["hero_title", "hero_lead"])
        self.content_type = ContentType.objects.get_for_model(StorePageCopy)
        PageSection.objects.filter(content_type=self.content_type, object_id=self.store_copy.pk).delete()

    def test_store_home_uses_standard_layout_when_no_page_sections_exist(self):
        response = self.client.get(self.store_url, secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "__default_store_title__")
        self.assertNotContains(response, "builder-section")

    def test_store_home_renders_page_builder_sections_when_present(self):
        PageSection.objects.create(
            content_type=self.content_type,
            object_id=self.store_copy.pk,
            section_type=PageSection.SectionType.TEXT,
            order=10,
            config={
                "title": "__builder_store_title__",
                "body": "__builder_store_body__",
            },
        )

        response = self.client.get(self.store_url, secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "__builder_store_title__")
        self.assertContains(response, "__builder_store_body__")
        self.assertContains(response, "builder-section--text")
        self.assertNotContains(response, "__default_store_title__")
