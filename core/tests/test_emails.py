from django.test import SimpleTestCase

from core import emails


class SafeValueTests(SimpleTestCase):
    def test_safe_handles_none(self):
        self.assertEqual(emails._safe(None), "")

    def test_safe_escapes_html(self):
        self.assertEqual(emails._safe("<b>Hi</b>"), "&lt;b&gt;Hi&lt;/b&gt;")


class FormatUrlTests(SimpleTestCase):
    def test_format_url_prefixes_https(self):
        self.assertEqual(emails._format_url("example.com"), "https://example.com")

    def test_format_url_preserves_http(self):
        self.assertEqual(emails._format_url("http://example.com"), "http://example.com")


class CleanRowsTests(SimpleTestCase):
    def test_clean_rows_strips_and_filters(self):
        rows = [("Order #", " 123 "), ("Empty", ""), ("None", None), (456, "  ")]

        self.assertEqual(emails._clean_rows(rows), [("Order #", "123")])

    def test_clean_rows_casts_label(self):
        rows = [(123, "Value")]

        self.assertEqual(emails._clean_rows(rows), [("123", "Value")])


class CleanItemsTests(SimpleTestCase):
    def test_clean_items_keeps_partial_rows(self):
        items = [("Widget", 2), (" ", None), (None, "3")]

        self.assertEqual(emails._clean_items(items), [("Widget", "2"), ("", "3")])


class CleanLinkRowsTests(SimpleTestCase):
    def test_clean_link_rows_requires_label_and_url(self):
        rows = [("Track", "example.com/track"), ("Missing", ""), (" ", "example.com")]

        self.assertEqual(emails._clean_link_rows(rows), [("Track", "example.com/track")])
