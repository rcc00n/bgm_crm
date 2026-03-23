from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from store.models import CarMake, CarModel, Category, Product


class ProductCompanionItemsTests(TestCase):
    def setUp(self):
        self.fuel_category = Category.objects.create(name="Fuel System", slug="fuel-system")
        self.engine_category = Category.objects.create(name="Engine", slug="engine")
        self.exhaust_category = Category.objects.create(name="Exhaust", slug="exhaust")
        self.merch_category = Category.objects.create(name="Merch", slug="merch")
        make = CarMake.objects.create(name="Ford")
        self.platform = CarModel.objects.create(make=make, name="F-250", year_from=2020, year_to=2024)

    def _product(self, **kwargs) -> Product:
        defaults = {
            "price": Decimal("10.00"),
            "is_active": True,
        }
        defaults.update(kwargs)
        return Product.objects.create(**defaults)

    def test_get_companion_items_prefers_relevant_non_merch_products(self):
        product = self._product(
            name="FASS Return Line Fitting",
            slug="fass-return-line-fitting",
            sku="FASS-1003",
            category=self.fuel_category,
            short_description="Fuel system fitting for regulated return setups.",
        )
        product.compatible_models.add(self.platform)

        top_match = self._product(
            name="FASS Return Line Hose",
            slug="fass-return-line-hose",
            sku="FASS-HOSE-1",
            category=self.fuel_category,
            short_description="Fuel system hose for FASS return plumbing.",
        )
        top_match.compatible_models.add(self.platform)

        second_match = self._product(
            name="Fuel Bowl Delete Plug",
            slug="fuel-bowl-delete-plug",
            sku="FUEL-PLUG-1",
            category=self.engine_category,
            short_description="Fuel delete plug for matching regulated return installs.",
        )
        second_match.compatible_models.add(self.platform)

        third_match = self._product(
            name="Draw Straw Adapter",
            slug="draw-straw-adapter",
            sku="DRAW-STRAW-1",
            category=self.fuel_category,
            short_description="Fuel pickup adapter for supporting return-side installs.",
        )

        merch = self._product(
            name="FASS Shop Tee",
            slug="merch-fass-shop-tee",
            sku="PF-FASS-TEE-1",
            category=self.merch_category,
            short_description="Merch should never show as a build companion.",
        )
        merch.compatible_models.add(self.platform)

        unrelated = self._product(
            name="Exhaust Hanger",
            slug="exhaust-hanger",
            sku="EXH-HANGER-1",
            category=self.exhaust_category,
            short_description="Unrelated catalog item.",
        )

        companions = product.get_companion_items(limit=3)

        self.assertEqual(
            [item.slug for item in companions],
            [top_match.slug, second_match.slug, third_match.slug],
        )
        self.assertNotIn(merch.pk, [item.pk for item in companions])
        self.assertNotIn(unrelated.pk, [item.pk for item in companions])

    def test_product_detail_renders_go_along_section_before_quote_request(self):
        product = self._product(
            name="Bridge Deck",
            slug="bridge-deck",
            sku="BGM-001",
            category=self.fuel_category,
            short_description="Main product detail page target.",
        )
        self._product(
            name="Bridge Deck Hardware",
            slug="bridge-deck-hardware",
            sku="BGM-002",
            category=self.fuel_category,
            short_description="Companion part.",
        )

        response = self.client.get(reverse("store:store-product", kwargs={"slug": product.slug}), follow=True)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('class="section__title product-detail__title"', content)
        self.assertLess(
            content.index("Items that go along to complete your build"),
            content.index("Share the inputs, we’ll send the plan"),
        )
