from decimal import Decimal

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from store.models import Category, Product, CustomFitmentRequest


class ProductDetailQuoteFormTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Decks", slug="decks")
        self.product = Product.objects.create(
            name="Bridge Deck",
            slug="bridge-deck",
            sku="BGM-001",
            category=self.category,
            price=Decimal("1999.00"),
        )
        self.url = reverse("store:store-product", kwargs={"slug": self.product.slug})

    def test_quote_submission_creates_request_and_sends_email(self):
        payload = {
            "form_type": "custom_fitment",
            "customer_name": "Jane Builder",
            "email": "jane@example.com",
            "phone": "+1 555 0100",
            "vehicle": "2020 F-350 crew cab",
            "performance_goals": "Tow + chase truck duties",
            "timeline": "Need it next month",
            "message": "Also need powder coat.",
        }

        response = self.client.post(self.url, payload, follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("#quote-request", response.url)

        self.assertEqual(CustomFitmentRequest.objects.count(), 1)
        req = CustomFitmentRequest.objects.get()
        self.assertEqual(req.product, self.product)
        self.assertEqual(req.product_name, self.product.name)
        self.assertEqual(req.customer_name, payload["customer_name"])
        self.assertEqual(req.status, CustomFitmentRequest.Status.NEW)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Custom fitment request", mail.outbox[0].subject)
        self.assertIn(self.product.name, mail.outbox[0].body)

    def test_invalid_submission_shows_errors(self):
        payload = {
            "form_type": "custom_fitment",
            "customer_name": "Jane Builder",
            # missing email
        }

        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        form = response.context["quote_form"]
        self.assertIn("email", form.errors)
        self.assertIn("Please correct the fields", response.content.decode())
        self.assertEqual(CustomFitmentRequest.objects.count(), 0)
