from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from store.models import Category, Product


class ProductAdminChangeFormTests(TestCase):
    def setUp(self):
        self.superuser = get_user_model().objects.create_superuser(
            username="product-admin",
            email="product-admin@example.com",
            password="StrongPass123!",
        )
        self.category = Category.objects.create(name="Admin Layout", slug="admin-layout")
        self.product = Product.objects.create(
            name="Admin Layout Product",
            slug="admin-layout-product",
            sku="ADM-LAYOUT-1",
            category=self.category,
            price=Decimal("149.00"),
            inventory=5,
            is_active=True,
        )
        self.client.force_login(self.superuser)

    def test_change_form_uses_custom_product_workspace_layout(self):
        response = self.client.get(
            reverse("admin:store_product_change", args=[self.product.pk]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "product-admin-shell")
        self.assertContains(response, "product-admin-hero")
        self.assertContains(response, "Catalog identity")
        self.assertContains(response, "Pricing &amp; stock")
        self.assertContains(response, "Product options")
        self.assertContains(response, "Product images")
        self.assertContains(response, "Show Armadillo vs Smooth Criminal guide")
