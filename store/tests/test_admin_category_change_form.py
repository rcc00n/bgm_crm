from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from store.models import Category, Product


class CategoryAdminChangeFormTests(TestCase):
    def setUp(self):
        self.superuser = get_user_model().objects.create_superuser(
            username="category-admin",
            email="category-admin@example.com",
            password="StrongPass123!",
        )
        self.client.force_login(self.superuser)

    def test_change_form_lists_products_in_category(self):
        category = Category.objects.create(name="Bumpers", slug="bumpers")
        active_product = Product.objects.create(
            name="Alpha Bumper",
            slug="alpha-bumper",
            sku="BUMP-ALPHA",
            category=category,
            price=Decimal("1299.00"),
            inventory=4,
            is_active=True,
        )
        inactive_product = Product.objects.create(
            name="Beta Bumper",
            slug="beta-bumper",
            sku="BUMP-BETA",
            category=category,
            price=Decimal("999.00"),
            inventory=0,
            is_active=False,
        )

        response = self.client.get(
            reverse("admin:store_category_change", args=[category.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2 products in this category: 1 active product, 1 inactive product.")
        self.assertContains(response, active_product.name)
        self.assertContains(response, inactive_product.name)
        self.assertContains(response, reverse("admin:store_product_change", args=[active_product.pk]))
        self.assertContains(response, reverse("admin:store_product_change", args=[inactive_product.pk]))
        self.assertContains(response, "inactive")

    def test_change_form_shows_empty_state_when_category_has_no_products(self):
        category = Category.objects.create(name="Empty Category", slug="empty-category")

        response = self.client.get(
            reverse("admin:store_category_change", args=[category.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No products in this category yet.")
