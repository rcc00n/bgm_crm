from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

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
