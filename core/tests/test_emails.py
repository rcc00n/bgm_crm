from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase

from core import emails


@contextmanager
def _patched_email_branding():
    with patch.multiple(
        emails,
        email_brand_name=lambda: "BGM",
        email_brand_tagline=lambda: "Tagline",
        email_company_address=lambda: "123 Road",
        email_company_phone=lambda: "555-0100",
        email_company_website=lambda: "bgm.example",
        email_accent_color=lambda: "#ff0000",
        email_dark_color=lambda: "#111111",
        email_bg_color=lambda: "#000000",
    ):
        yield


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


class BuildEmailHtmlTests(SimpleTestCase):
    def test_build_email_html_includes_sections(self):
        with _patched_email_branding():
            html = emails.build_email_html(
                title="Order <b>Ready</b>",
                preheader="View <strong>order</strong>",
                greeting="Hi <script>alert(1)</script>",
                intro_lines=["Line 1", "Line 2"],
                detail_rows=[("Order #", " 123 "), ("Empty", " ")],
                item_rows=[("Widget", 2), ("", "")],
                summary_rows=[("Total", "$50")],
                notice_title="Note",
                notice_lines=["Notice line", ""],
                footer_lines=["Footer line", ""],
                cta_label="View Order",
                cta_url="example.com/order",
            )

        self.assertIn("&lt;b&gt;Ready&lt;/b&gt;", html)
        self.assertIn("&lt;strong&gt;order&lt;/strong&gt;", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("Order #", html)
        self.assertIn(">123<", html)
        self.assertNotIn("Empty", html)
        self.assertIn("Widget", html)
        self.assertIn(">2<", html)
        self.assertIn("Total", html)
        self.assertIn("$50", html)
        self.assertIn("Notice line", html)
        self.assertIn("Footer line", html)
        self.assertIn("View Order", html)
        self.assertIn("https://example.com/order", html)
