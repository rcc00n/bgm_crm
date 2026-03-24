from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from store.fitment import (
    COMMERCIAL_COMPATIBILITY_NOTE,
    UNIVERSAL_COMPATIBILITY_NOTE,
    infer_fitment,
    suggested_category_name,
    sync_consumer_vehicle_catalog,
)
from store.models import CarMake, CarModel, Category, Product


class FitmentInferenceTests(TestCase):
    def test_infer_fitment_marks_universal_titles_as_universal(self):
        result = infer_fitment(name="SOTF Harness (Universal)", sku="541-03100")

        self.assertTrue(result.is_universal)
        self.assertEqual(result.note, UNIVERSAL_COMPATIBILITY_NOTE)
        self.assertGreater(len(result.specs), 20)

    def test_infer_fitment_maps_super_duty_powerstroke_title_to_ford_hd_models(self):
        result = infer_fitment(
            name='Aluminized 4" Cat & DPF Race Pipe | Ford 6.4L F250/F350/F450/F550 Powerstroke (2008-2010)',
            sku="156-800124",
        )

        self.assertTrue(result.is_consumer_specific)
        self.assertEqual(
            {(spec.make, spec.model, spec.year_from, spec.year_to) for spec in result.specs},
            {
                ("Ford", "F-250", 2008, 2010),
                ("Ford", "F-350", 2008, 2010),
                ("Ford", "F-450", 2008, 2010),
                ("Ford", "F-550", 2008, 2010),
            },
        )

    def test_infer_fitment_maps_code_based_fass_ram_mounting_package(self):
        result = infer_fitment(name="FASS Mounting Package - DIFSRAM1001", sku="MP-A9094")

        self.assertTrue(result.is_consumer_specific)
        self.assertEqual(
            {(spec.make, spec.model, spec.year_from, spec.year_to) for spec in result.specs},
            {
                ("Ram / Dodge", "2500", 2010, 2018),
                ("Ram / Dodge", "3500", 2010, 2018),
            },
        )

    def test_infer_fitment_keeps_class_8_titles_out_of_consumer_fitment(self):
        result = infer_fitment(name="FASS - Class 8 100 GPH/16-18 PSI", sku="TS100G")

        self.assertTrue(result.is_commercial)
        self.assertEqual(result.note, COMMERCIAL_COMPATIBILITY_NOTE)
        self.assertEqual(result.specs, tuple())

    def test_suggested_category_name_recategorizes_active_uncategorized_engine_parts(self):
        suggestion = suggested_category_name(
            current_category_name="Uncategorized",
            product_name="CCV Upgrade Kit (2011-2025 Powerstroke 6.7L)",
        )

        self.assertEqual(suggestion, "Motor Vehicle Engine Parts")


class StorefrontFitmentFilterTests(TestCase):
    def setUp(self):
        sync_consumer_vehicle_catalog(apply=True)
        self.store_url = reverse("store:store")
        self.category = Category.objects.create(name="Exhaust", slug="exhaust")
        self.ford = CarMake.objects.get(name="Ford")
        self.f250_broad = CarModel.objects.get(make=self.ford, name="F-250", year_from=1999, year_to=None)
        self.f250_specific = CarModel.objects.create(make=self.ford, name="F-250", year_from=2008, year_to=2010)
        self.f350_specific = CarModel.objects.create(make=self.ford, name="F-350", year_from=2008, year_to=2010)

        self.universal_product = Product.objects.create(
            name="Universal Ford Part",
            slug="universal-ford-part",
            sku="UF-001",
            category=self.category,
            price=Decimal("10.00"),
            is_active=True,
        )
        self.universal_product.compatible_models.add(self.f250_broad)

        self.specific_product = Product.objects.create(
            name="2008-2010 Ford F-250 Part",
            slug="specific-f250-part",
            sku="SF-001",
            category=self.category,
            price=Decimal("10.00"),
            is_active=True,
        )
        self.specific_product.compatible_models.add(self.f250_specific)

        self.other_model_product = Product.objects.create(
            name="2008-2010 Ford F-350 Part",
            slug="specific-f350-part",
            sku="SF-002",
            category=self.category,
            price=Decimal("10.00"),
            is_active=True,
        )
        self.other_model_product.compatible_models.add(self.f350_specific)

    def test_storefront_json_deduplicates_model_options_by_name(self):
        response = self.client.get(self.store_url, {"format": "json", "make": self.ford.pk})

        self.assertEqual(response.status_code, 200)
        models = response.json()["filters"]["available"]["models"]
        f250_entries = [row for row in models if row["id"] == "F-250"]
        self.assertEqual(len(f250_entries), 1)

    def test_storefront_filters_by_model_name_and_year_overlap(self):
        response = self.client.get(
            self.store_url,
            {
                "format": "json",
                "make": self.ford.pk,
                "model": "F-250",
                "year": 2009,
            },
        )

        self.assertEqual(response.status_code, 200)
        names = [row["name"] for row in response.json()["catalog"]["products"]]
        self.assertEqual(names, ["2008-2010 Ford F-250 Part", "Universal Ford Part"])

    def test_storefront_year_filter_excludes_non_overlapping_fitment_ranges(self):
        response = self.client.get(
            self.store_url,
            {
                "format": "json",
                "make": self.ford.pk,
                "model": "F-250",
                "year": 2005,
            },
        )

        self.assertEqual(response.status_code, 200)
        names = [row["name"] for row in response.json()["catalog"]["products"]]
        self.assertEqual(names, ["Universal Ford Part"])
