from django.test import SimpleTestCase

from store.utils_merch import normalize_merch_category


class NormalizeMerchCategoryTests(SimpleTestCase):
    def test_blank_label_returns_empty_values(self):
        self.assertEqual(normalize_merch_category(""), ("", ""))

    def test_groups_hoodie_like_labels(self):
        self.assertEqual(normalize_merch_category("Heavyweight Pullover Hoodie"), ("hoodies", "Hoodies"))

    def test_groups_hat_like_labels(self):
        self.assertEqual(normalize_merch_category("Classic Snapback Cap"), ("hats", "Hats"))

    def test_fallback_skips_stopwords_and_pluralizes_meaningful_word(self):
        self.assertEqual(normalize_merch_category("Premium Banner"), ("banners", "Banners"))

    def test_symbol_only_label_falls_back_to_merch_key(self):
        self.assertEqual(normalize_merch_category("###"), ("merch", "###"))
