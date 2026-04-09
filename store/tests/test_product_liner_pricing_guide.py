from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from store.models import Category, Product


class ProductLinerPricingGuideTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Bumpers", slug="bumpers")

    def _product(self, *, show_liner_pricing_guide: bool) -> Product:
        return Product.objects.create(
            name="Front Bumper",
            slug=f"front-bumper-{'guide' if show_liner_pricing_guide else 'plain'}",
            sku=f"BGM-BUMPER-{'GUIDE' if show_liner_pricing_guide else 'PLAIN'}",
            category=self.category,
            price=Decimal("1499.00"),
            is_active=True,
            is_in_house=True,
            show_liner_pricing_guide=show_liner_pricing_guide,
        )

    def test_product_detail_renders_liner_pricing_guide_when_enabled(self):
        product = self._product(show_liner_pricing_guide=True)

        response = self.client.get(reverse("store:store-product", kwargs={"slug": product.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Armadillo vs Smooth Criminal")
        self.assertContains(response, "Smooth Criminal Liner gives you a smoother")
        self.assertContains(response, "data-liner-guide-open")

    def test_product_detail_hides_liner_pricing_guide_when_disabled(self):
        product = self._product(show_liner_pricing_guide=False)

        response = self.client.get(reverse("store:store-product", kwargs={"slug": product.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Armadillo vs Smooth Criminal")
        self.assertNotContains(response, "data-liner-guide-open")
