from django.test import TestCase
from django.urls import reverse

from core.models import HomePageCopy, HomePageFAQItem


class HomePageFaqItemsTests(TestCase):
    def setUp(self):
        self.home_copy = HomePageCopy.get_solo()
        HomePageFAQItem.objects.filter(home_page_copy=self.home_copy).delete()

    def test_home_page_renders_only_published_faq_items(self):
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

        resp = self.client.get(reverse("home"))
        self.assertContains(resp, "__published_q__")
        self.assertContains(resp, "__published_a__")
        self.assertNotContains(resp, "__draft_q__")
        self.assertNotContains(resp, "__draft_a__")

    def test_home_page_hides_legacy_faq_when_no_published_items(self):
        # Ensure legacy fields do not "leak" back in when using the new FAQ model.
        self.home_copy.faq_1_question = "__legacy_q__"
        self.home_copy.faq_1_answer = "__legacy_a__"
        self.home_copy.save(update_fields=["faq_1_question", "faq_1_answer"])

        HomePageFAQItem.objects.create(
            home_page_copy=self.home_copy,
            order=1,
            question="__draft_q_only__",
            answer="__draft_a_only__",
            is_published=False,
        )

        resp = self.client.get(reverse("home"))
        self.assertNotContains(resp, "__legacy_q__")
        self.assertNotContains(resp, "__legacy_a__")
        self.assertNotContains(resp, "__draft_q_only__")
        self.assertNotContains(resp, "__draft_a_only__")

