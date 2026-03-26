from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from store.models import Category, Product


class CategoryRedirectTests(TestCase):
    def _create_product(self, *, category: Category, name: str, slug: str, sku: str, is_active: bool = True) -> Product:
        return Product.objects.create(
            name=name,
            slug=slug,
            sku=sku,
            category=category,
            price=Decimal("10.00"),
            is_active=is_active,
        )

    def test_category_with_single_active_product_redirects_to_product_page(self):
        category = Category.objects.create(name="Bumpers", slug="bumpers")
        product = self._create_product(
            category=category,
            name="Front Bumper",
            slug="front-bumper",
            sku="BGM-BUMPER-1",
        )

        response = self.client.get(reverse("store:store-category", kwargs={"slug": category.slug}), secure=True)

        self.assertRedirects(
            response,
            reverse("store:store-product", kwargs={"slug": product.slug}),
            fetch_redirect_response=False,
        )

    def test_category_with_multiple_active_products_renders_category_page(self):
        category = Category.objects.create(name="Exhaust", slug="exhaust")
        self._create_product(
            category=category,
            name="Exhaust Kit A",
            slug="exhaust-kit-a",
            sku="BGM-EXH-1",
        )
        self._create_product(
            category=category,
            name="Exhaust Kit B",
            slug="exhaust-kit-b",
            sku="BGM-EXH-2",
        )

        response = self.client.get(reverse("store:store-category", kwargs={"slug": category.slug}), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "store/category_list.html")
