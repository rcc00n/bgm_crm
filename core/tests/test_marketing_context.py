from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.template import Context, Template

from core.context_processors_core import marketing_tags


class MarketingTagsTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(MARKETING={})
    def test_site_name_defaults_to_bgm(self):
        request = self.factory.get("/")
        payload = marketing_tags(request)
        self.assertEqual(payload["marketing"]["site_name"], "BGM")

    @override_settings(MARKETING={"site_name": "BGM Customs"})
    def test_site_name_normalizes_legacy_default(self):
        request = self.factory.get("/")
        payload = marketing_tags(request)
        self.assertEqual(payload["marketing"]["site_name"], "BGM")


class MarketingHeadTemplateTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_meta_tags_render_plain_text_description(self):
        template = Template("{% include 'includes/marketing_head.html' %}")
        request = self.factory.get("/")
        request.user = AnonymousUser()

        context = Context(
            {
                "request": request,
                "meta_title": "BGM — Performance Builds",
                "meta_description": "<p>Performance-driven builds</p><p>Detailed &amp; tuned</p>",
                "marketing": {
                    "site_name": "BGM",
                    "default_description": "",
                    "default_image": "/static/img/preview.jpg",
                    "default_image_absolute": "https://example.com/static/img/preview.jpg",
                    "organization_logo": "/static/img/logo.jpg",
                    "organization_logo_absolute": "https://example.com/static/img/logo.jpg",
                    "organization_same_as": [],
                    "default_keywords": "",
                    "canonical_url": "https://example.com/",
                    "page_url": "https://example.com/",
                    "origin": "https://example.com",
                    "google_tag_manager_id": "",
                    "google_ads_id": "",
                    "google_ads_conversion_label": "",
                    "google_ads_send_page_view": False,
                },
            }
        )

        rendered = template.render(context)
        self.assertIn('meta property="og:description" content="Performance-driven builds Detailed &amp; tuned"', rendered)
        self.assertNotIn("&lt;p&gt;", rendered)
