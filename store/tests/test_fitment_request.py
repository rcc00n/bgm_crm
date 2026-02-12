from decimal import Decimal
import io

from django.core import mail
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from store.models import Category, Product, CustomFitmentRequest
from core.models import ClientFile


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
            "submodel": "Platinum",
            "performance_goals": "Tow + chase truck duties",
            "budget": "Up to $15k",
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
        self.assertEqual(req.submodel, payload["submodel"])
        self.assertEqual(req.budget, payload["budget"])
        self.assertEqual(req.status, CustomFitmentRequest.Status.NEW)

        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Custom fitment request", mail.outbox[0].subject)
        self.assertIn(self.product.name, mail.outbox[0].body)
        self.assertIn("request received", mail.outbox[1].subject.lower())
        self.assertIn("will reach out soon", mail.outbox[1].body.lower())

    def test_quote_submission_with_reference_photo_syncs_to_client_files(self):
        user = User.objects.create_user(
            username="fitment-client",
            email="fitment.client@example.com",
            password="pass12345",
        )
        self.client.force_login(user)

        image_buffer = io.BytesIO()
        Image.new("RGB", (12, 12), color=(220, 10, 10)).save(image_buffer, format="PNG")
        image_buffer.seek(0)
        upload = SimpleUploadedFile(
            "fitment.png",
            image_buffer.read(),
            content_type="image/png",
        )

        payload = {
            "form_type": "custom_fitment",
            "customer_name": "Fitment Client",
            "email": "fitment.client@example.com",
            "phone": "+1 555 0111",
            "vehicle": "2023 Ram 2500",
            "message": "Need custom offset.",
        }

        response = self.client.post(self.url, payload | {"reference_image": upload}, follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CustomFitmentRequest.objects.count(), 1)
        req = CustomFitmentRequest.objects.get()
        self.assertTrue(bool(req.reference_image))

        self.assertEqual(ClientFile.objects.filter(user=user).count(), 1)
        saved = ClientFile.objects.filter(user=user).first()
        self.assertIsNotNone(saved)
        self.assertIn("Custom fitment reference", saved.description)

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
