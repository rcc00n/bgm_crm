from decimal import Decimal

from django.test import TestCase

from store.forms_store import CustomFitmentRequestForm, ProductFilterForm
from store.models import CarMake, CarModel, Category, Product


class CustomFitmentRequestFormTests(TestCase):
    def test_clean_phone_strips_unwanted_characters(self):
        form = CustomFitmentRequestForm(
            data={
                "customer_name": "Taylor",
                "email": "taylor@example.com",
                "phone": "403.555.0100",
                "vehicle": "2020 F-150",
                "submodel": "XLT",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["phone"], "4035550100")


class ProductFilterFormTests(TestCase):
    def setUp(self):
        self.category_active = Category.objects.create(name="Active", slug="active")
        self.category_inactive = Category.objects.create(name="Inactive", slug="inactive")
        Product.objects.create(
            name="Active Product",
            slug="active-product",
            sku="SKU-1",
            category=self.category_active,
            price=Decimal("10.00"),
            is_active=True,
        )
        Product.objects.create(
            name="Inactive Product",
            slug="inactive-product",
            sku="SKU-2",
            category=self.category_inactive,
            price=Decimal("10.00"),
            is_active=False,
        )
        self.make_a = CarMake.objects.create(name="Make A")
        self.make_b = CarMake.objects.create(name="Make B")
        self.model_a1 = CarModel.objects.create(make=self.make_a, name="Model A1")
        self.model_b1 = CarModel.objects.create(make=self.make_b, name="Model B1")

    def test_category_queryset_filters_to_active_products(self):
        form = ProductFilterForm()
        self.assertTrue(form.fields["category"].queryset.filter(pk=self.category_active.pk).exists())
        self.assertFalse(form.fields["category"].queryset.filter(pk=self.category_inactive.pk).exists())

    def test_model_queryset_filters_by_make_when_bound(self):
        form = ProductFilterForm(data={"make": self.make_a.pk})
        self.assertEqual(list(form.fields["model"].queryset), [self.model_a1])
