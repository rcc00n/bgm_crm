from types import SimpleNamespace
from unittest.mock import patch

from django.db.utils import OperationalError
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase

from core.context_processors_core import site_contact


class SiteContactContextTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("core.context_processors_core.SiteContactSettings.get_solo")
    def test_site_contact_uses_admin_values(self, get_solo_mock):
        get_solo_mock.return_value = SimpleNamespace(
            contact_email="hello@example.com",
            office_phone="+14035550111",
            office_phone_display="(403) 555-0111",
            text_phone="+15875550101",
            text_phone_display="(587) 555-0101",
        )

        payload = site_contact(self.factory.get("/"))

        self.assertEqual(payload["site_contact"]["email"], "hello@example.com")
        self.assertEqual(payload["site_contact"]["office_phone"], "+14035550111")
        self.assertEqual(payload["site_contact"]["text_phone"], "+15875550101")

    @patch("core.context_processors_core.SiteContactSettings.get_solo")
    def test_site_contact_falls_back_when_table_is_unavailable(self, get_solo_mock):
        get_solo_mock.side_effect = OperationalError("missing table")

        payload = site_contact(self.factory.get("/"))

        self.assertEqual(payload["site_contact"]["email"], "support@badguymotors.com")
        self.assertEqual(payload["site_contact"]["office_phone"], "+14035250432")
        self.assertEqual(payload["site_contact"]["text_phone"], "+15874060101")

    def test_template_can_render_different_call_and_text_numbers(self):
        template = Template(
            '<a href="tel:{{ site_contact.office_phone }}">call</a>'
            '<a href="sms:{{ site_contact.text_phone }}">text</a>'
        )
        rendered = template.render(
            Context(
                {
                    "site_contact": {
                        "office_phone": "+14035550111",
                        "text_phone": "+15875550101",
                    }
                }
            )
        )

        self.assertIn('href="tel:+14035550111"', rendered)
        self.assertIn('href="sms:+15875550101"', rendered)
