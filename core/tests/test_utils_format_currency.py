from django.test import SimpleTestCase, override_settings

from core.utils import format_currency


class FormatCurrencyTests(SimpleTestCase):
    @override_settings(DEFAULT_CURRENCY_CODE="CAD", DEFAULT_CURRENCY_SYMBOL="$")
    def test_formats_with_code_and_symbol(self):
        self.assertEqual(format_currency(1234.5), "CAD $1,234.50")

    @override_settings(DEFAULT_CURRENCY_CODE="CAD", DEFAULT_CURRENCY_SYMBOL="$")
    def test_formats_without_code(self):
        self.assertEqual(format_currency(1234.5, include_code=False), "$1,234.50")

    @override_settings(DEFAULT_CURRENCY_CODE="", DEFAULT_CURRENCY_SYMBOL="$")
    def test_omits_empty_code(self):
        self.assertEqual(format_currency("1"), "$1.00")
