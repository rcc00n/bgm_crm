from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from store.models import Category, Product


class AdminWorkspaceUiTests(TestCase):
    def setUp(self):
        self.superuser = get_user_model().objects.create_superuser(
            username="workspace-admin",
            email="workspace-admin@example.com",
            password="StrongPass123!",
        )
        self.client.force_login(self.superuser)

    def test_workspace_hub_includes_rule_to_hide_empty_header_strip(self):
        response = self.client.get(reverse("admin-workspace-hub", kwargs={"slug": "scheduling-shop"}), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Scheduling &amp; Shop")
        self.assertContains(
            response,
            ".content.border-bottom.mb-2:not(:has(h1:not(:empty))):not(:has(.breadcrumb)):not(:has(.breadcrumbs))",
        )

    def test_product_changelist_still_renders_heading_and_breadcrumbs(self):
        category = Category.objects.create(name="Admin Products", slug="admin-products")
        Product.objects.create(
            name="Admin Test Product",
            slug="admin-test-product",
            sku="BGM-ADMIN-TEST-1",
            category=category,
            price=Decimal("99.00"),
            inventory=3,
            is_active=True,
        )

        response = self.client.get(reverse("admin:store_product_changelist"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inventory watch")
        self.assertContains(response, "<ol class=\"breadcrumb\">", html=False)
        self.assertContains(response, "/admin/store/", html=False)
        self.assertContains(response, "Products")
