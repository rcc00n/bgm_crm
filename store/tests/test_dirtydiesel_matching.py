from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase

from store.dirtydiesel_import.matching import (
    _score_name_match,
    build_compact_sku_index,
    build_name_index,
    build_name_profile,
    build_sku_index,
    match_catalog_product,
)
from store.dirtydiesel_import.types import SourceProduct


class DirtyDieselMatchingTests(SimpleTestCase):
    def _product(self, *, name: str, sku: str = "internal-sku", category_name: str = "Software", category_slug: str = "software"):
        return SimpleNamespace(
            name=name,
            sku=sku,
            category=SimpleNamespace(name=category_name, slug=category_slug),
        )

    def test_exact_name_same_product_variants_resolve_high_confidence(self):
        source_products = [
            SourceProduct(
                product_id=101,
                variant_id=1,
                sku="GDP11002",
                product_name="EZ Lynk Auto Agent 3 w/ GDP Support Pack (Ford/GM/Ram/Nissan)",
                variant_name="Lifetime Support Pack",
                supplier_name="GDP",
                supplier_category="Tuners",
                product_page_url="https://supplier.example/products/ez-lynk-support-pack",
                image_urls=("https://cdn.example.com/aa3-lifetime.jpg",),
            ),
            SourceProduct(
                product_id=101,
                variant_id=2,
                sku="GDP11003",
                product_name="EZ Lynk Auto Agent 3 w/ GDP Support Pack (Ford/GM/Ram/Nissan)",
                variant_name="4 Week Support Pack",
                supplier_name="GDP",
                supplier_category="Tuners",
                product_page_url="https://supplier.example/products/ez-lynk-support-pack",
                image_urls=("https://cdn.example.com/aa3-4week.jpg",),
            ),
        ]
        source_by_sku = build_sku_index(source_products)
        source_by_compact_sku = build_compact_sku_index(source_products)
        source_candidates, token_index, exact_name_index = build_name_index(source_products)

        match = match_catalog_product(
            self._product(name="EZ Lynk Auto Agent 3 w/ GDP Support Pack (Ford/GM/Ram/Nissan)"),
            source_by_sku=source_by_sku,
            source_by_compact_sku=source_by_compact_sku,
            source_candidates=source_candidates,
            token_index=token_index,
            exact_name_index=exact_name_index,
            allow_name_match=True,
        )

        self.assertEqual(match.confidence, "high")
        self.assertEqual(match.reason, "exact_name_same_product")
        self.assertEqual(match.source.product_id, 101)

    def test_exact_name_strips_supplier_prefix(self):
        source_products = [
            SourceProduct(
                product_id=202,
                variant_id=11,
                sku="355-02301",
                product_name="DIESELR Cat & DPF Race Pipe (2014-2018 Ram 1500 3.0L EcoDiesel)",
                variant_name='3" / No Muffler',
                supplier_name="Dieselr Parts",
                supplier_category="Exhaust",
                product_page_url="https://supplier.example/products/cat-dpf-race-pipe",
                image_urls=("https://cdn.example.com/race-pipe.jpg",),
            ),
        ]
        source_by_sku = build_sku_index(source_products)
        source_by_compact_sku = build_compact_sku_index(source_products)
        source_candidates, token_index, exact_name_index = build_name_index(source_products)

        match = match_catalog_product(
            self._product(
                name="Cat & DPF Race Pipe (2014-2018 Ram 1500 3.0L EcoDiesel)",
                category_slug="vehicles-parts-vehicle-parts-accessories-motor-v-2",
                category_name="Motor Vehicle Exhaust Parts",
            ),
            source_by_sku=source_by_sku,
            source_by_compact_sku=source_by_compact_sku,
            source_candidates=source_candidates,
            token_index=token_index,
            exact_name_index=exact_name_index,
            allow_name_match=True,
        )

        self.assertEqual(match.confidence, "high")
        self.assertEqual(match.reason, "exact_name")
        self.assertEqual(match.source.sku, "355-02301")

    def test_conflicting_platform_tokens_do_not_name_match(self):
        product_profile = build_name_profile("MPVI4 Tune Files (2017-2023 Duramax L5P 6.6L)")
        candidate_profile = build_name_profile("SCT Tune Files (2017-2023 Duramax L5P 6.6L)")

        self.assertIsNone(_score_name_match(product_profile, candidate_profile))
