from decimal import Decimal
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from store.models import Category, Product, StoreReview
from core.models import LeadSubmissionEvent
from core.services.lead_security import build_form_token


@override_settings(
    LEAD_FORM_MIN_AGE_SECONDS_STORE_REVIEW=0,
)
class StoreReviewViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.category = Category.objects.create(name="Wheels", slug="wheels")
        self.product = Product.objects.create(
            name="Test Product",
            slug="test-product",
            sku="SKU-REVIEW-1",
            category=self.category,
            price=Decimal("10.00"),
            is_active=True,
        )
        session = self.client.session
        session.save()

    def _review_token(self):
        session_key = self.client.session.session_key
        issued_at = timezone.now() - timedelta(seconds=10)
        return build_form_token(session_key=session_key, purpose="store_review", issued_at=issued_at)

    def test_product_review_submission_creates_pending_review(self):
        url = reverse("store:store-product", kwargs={"slug": self.product.slug})
        resp = self.client.post(
            url,
            data={
                "form_type": "product_review",
                "reviewer_name": "Alex",
                "reviewer_email": "alex@example.com",
                "reviewer_title": "BMW E90",
                "rating": 5,
                "title": "Great",
                "body": "Fitment was perfect.",
                "form_token": self._review_token(),
                "form_rendered_at": int(timezone.now().timestamp() * 1000) - 7000,
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("#reviews", resp["Location"])
        self.assertEqual(StoreReview.objects.count(), 1)
        review = StoreReview.objects.first()
        self.assertEqual(review.status, StoreReview.Status.PENDING)
        self.assertEqual(review.product_id, self.product.id)
        self.assertEqual(review.reviewer_name, "Alex")

    def test_product_detail_shows_only_approved_reviews(self):
        StoreReview.objects.create(
            product=self.product,
            reviewer_name="Pending",
            rating=5,
            body="Pending body",
            status=StoreReview.Status.PENDING,
        )
        StoreReview.objects.create(
            product=self.product,
            reviewer_name="Approved",
            rating=4,
            body="Approved body",
            status=StoreReview.Status.APPROVED,
        )

        url = reverse("store:store-product", kwargs={"slug": self.product.slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Approved body")
        self.assertNotContains(resp, "Pending body")

    def test_leave_review_submission_creates_pending_general_review(self):
        url = reverse("leave-review")
        resp = self.client.post(
            url,
            data={
                "reviewer_name": "Taylor",
                "reviewer_email": "taylor@example.com",
                "reviewer_title": "F-150",
                "rating": 5,
                "title": "Awesome",
                "body": "Great service and communication.",
                "form_token": self._review_token(),
                "form_rendered_at": int(timezone.now().timestamp() * 1000) - 7000,
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("?submitted=1", resp["Location"])
        self.assertEqual(StoreReview.objects.count(), 1)
        review = StoreReview.objects.first()
        self.assertEqual(review.status, StoreReview.Status.PENDING)
        self.assertIsNone(review.product_id)

    def test_review_without_token_is_rejected(self):
        url = reverse("leave-review")
        resp = self.client.post(
            url,
            data={
                "reviewer_name": "Taylor",
                "reviewer_email": "taylor@example.com",
                "reviewer_title": "F-150",
                "rating": 5,
                "title": "Awesome",
                "body": "Great service and communication.",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(StoreReview.objects.count(), 0)
        self.assertContains(resp, "Please refresh the page and try again.")
        self.assertTrue(
            LeadSubmissionEvent.objects.filter(
                form_type=LeadSubmissionEvent.FormType.STORE_REVIEW,
                outcome=LeadSubmissionEvent.Outcome.BLOCKED,
            ).exists()
        )

    def test_gibberish_review_name_is_suppressed(self):
        url = reverse("leave-review")
        resp = self.client.post(
            url,
            data={
                "reviewer_name": "EDCKCLPgWDeVXGyhjcmL",
                "reviewer_email": "jim@jimbianco.com",
                "reviewer_title": "",
                "rating": 5,
                "title": "Amazing",
                "body": "Everything was perfect and I totally recommend this place.",
                "form_token": self._review_token(),
                "form_rendered_at": int(timezone.now().timestamp() * 1000) - 7000,
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("?submitted=1", resp["Location"])
        self.assertEqual(StoreReview.objects.count(), 0)
        self.assertTrue(
            LeadSubmissionEvent.objects.filter(
                form_type=LeadSubmissionEvent.FormType.STORE_REVIEW,
                outcome=LeadSubmissionEvent.Outcome.BLOCKED,
                validation_errors__icontains="gibberish_name",
            ).exists()
        )
