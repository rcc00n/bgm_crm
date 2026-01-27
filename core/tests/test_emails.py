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
