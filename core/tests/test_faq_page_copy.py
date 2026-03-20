from django.test import TestCase
from django.urls import reverse

from core.models import FAQPageCopy, HomePageCopy, HomePageFAQItem


class FAQPageCopyTests(TestCase):
    def setUp(self):
        self.url = reverse("faq")
        self.home_copy = HomePageCopy.get_solo()
        self.faq_copy = FAQPageCopy.get_solo()
        HomePageFAQItem.objects.filter(home_page_copy=self.home_copy).delete()

    def test_faq_page_uses_faq_page_copy_content(self):
        self.home_copy.faq_title = "__old_home_title__"
        self.home_copy.faq_desc = "__old_home_desc__"
        self.home_copy.save(update_fields=["faq_title", "faq_desc"])

        self.faq_copy.meta_title = "__faq_meta__"
        self.faq_copy.page_title = "__faq_page_title__"
        self.faq_copy.page_lead = "__faq_page_lead__"
        self.faq_copy.empty_label = "__faq_empty__"
        self.faq_copy.save(
            update_fields=["meta_title", "page_title", "page_lead", "empty_label"]
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "__faq_page_title__")
        self.assertContains(response, "__faq_page_lead__")
        self.assertContains(response, "__faq_empty__")
        self.assertNotContains(response, "__old_home_title__")
        self.assertNotContains(response, "__old_home_desc__")
        self.assertEqual(response.context["faq_copy"].pk, self.faq_copy.pk)

    def test_faq_page_renders_only_published_faq_items(self):
        HomePageFAQItem.objects.create(
            home_page_copy=self.home_copy,
            order=1,
            question="__published_q__",
            answer="__published_a__",
            is_published=True,
        )
        HomePageFAQItem.objects.create(
            home_page_copy=self.home_copy,
            order=2,
            question="__draft_q__",
            answer="__draft_a__",
            is_published=False,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "__published_q__")
        self.assertContains(response, "__published_a__")
        self.assertNotContains(response, "__draft_q__")
        self.assertNotContains(response, "__draft_a__")
