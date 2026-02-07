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
