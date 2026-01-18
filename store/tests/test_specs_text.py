from django.test import SimpleTestCase

from store.forms_store import _smart_value, dump_specs_text, parse_specs_text


class SpecsTextParsingTests(SimpleTestCase):
    def test_smart_value_parses_basic_types(self):
        self.assertEqual(_smart_value('{"key": "value"}'), {"key": "value"})
        self.assertEqual(_smart_value("true"), True)
        self.assertEqual(_smart_value("12"), 12)
        self.assertEqual(_smart_value("12.5"), 12.5)

    def test_smart_value_parses_lists(self):
        self.assertEqual(_smart_value("a, b, c"), ["a", "b", "c"])

    def test_parse_specs_text_ignores_comments_and_malformed(self):
        text = "# comment\nsize: 42\nbad line\ncolors: red, blue\n"
        self.assertEqual(parse_specs_text(text), {"size": 42, "colors": ["red", "blue"]})

    def test_dump_specs_text_formats_values(self):
        specs = {"diameter": "76 mm", "fit": ["BMW", "Audi"], "meta": {"key": 1}}
        dumped = dump_specs_text(specs)
        self.assertIn("diameter: 76 mm", dumped)
        self.assertIn("fit: BMW, Audi", dumped)
        self.assertIn('meta: {"key": 1}', dumped)
