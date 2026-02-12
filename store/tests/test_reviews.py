from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from store.models import Category, Product, StoreReview


class StoreReviewViewTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Wheels", slug="wheels")
        self.product = Product.objects.create(
            name="Test Product",
            slug="test-product",
            sku="SKU-REVIEW-1",
            category=self.category,
            price=Decimal("10.00"),
            is_active=True,
        )

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
                "body": "Great service.",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("?submitted=1", resp["Location"])
        self.assertEqual(StoreReview.objects.count(), 1)
        review = StoreReview.objects.first()
        self.assertEqual(review.status, StoreReview.Status.PENDING)
        self.assertIsNone(review.product_id)

