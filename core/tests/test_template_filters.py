from django.test import SimpleTestCase


class SplitLinesFilterTests(SimpleTestCase):
    def test_split_lines_none(self):
        from core.templatetags.dealer_extras import split_lines

        self.assertEqual(split_lines(None), [])

    def test_split_lines_plain_text(self):
        from core.templatetags.dealer_extras import split_lines

        self.assertEqual(split_lines("a\n\n b \n"), ["a", "b"])

    def test_split_lines_html_paragraphs_and_entities(self):
        from core.templatetags.dealer_extras import split_lines

        value = "<p>A &amp; B</p><p>C &mdash; D</p>"
        self.assertEqual(split_lines(value), ["A & B", "C — D"])

    def test_split_lines_html_br_and_double_encoded(self):
        from core.templatetags.dealer_extras import split_lines

        value = "<p>Warranty &amp;amp; support<br>Ok &amp;mdash; good</p>"
        self.assertEqual(split_lines(value), ["Warranty & support", "Ok — good"])


class MetaTextFilterTests(SimpleTestCase):
    def test_meta_text_strips_html_and_collapses_whitespace(self):
        from core.templatetags.marketing_extras import meta_text

        value = "<p>Performance-driven builds</p>\n<p>Detailed &amp; tuned<br>for street</p>"
        self.assertEqual(
            meta_text(value),
            "Performance-driven builds Detailed & tuned for street",
        )

    def test_meta_text_decodes_double_encoded_entities(self):
        from core.templatetags.marketing_extras import meta_text

        value = "Warranty &amp;amp; support"
        self.assertEqual(meta_text(value), "Warranty & support")


class CopyExtrasFilterTests(SimpleTestCase):
    def test_suppress_symbol_only_copy_hides_placeholder_symbols(self):
        from core.templatetags.copy_extras import suppress_symbol_only_copy

        self.assertEqual(suppress_symbol_only_copy("*"), "")
        self.assertEqual(suppress_symbol_only_copy("(*)"), "")
        self.assertEqual(suppress_symbol_only_copy("."), "")

    def test_suppress_symbol_only_copy_keeps_real_copy(self):
        from core.templatetags.copy_extras import suppress_symbol_only_copy

        self.assertEqual(
            suppress_symbol_only_copy("Performance parts curated by BGM."),
            "Performance parts curated by BGM.",
        )
