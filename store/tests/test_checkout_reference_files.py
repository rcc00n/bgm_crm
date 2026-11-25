import io
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from core.models import ClientFile
from store.models import Category, Order, Product


@override_settings(
    ETRANSFER_EMAIL="payments@example.com",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class CheckoutReferenceFileTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Suspension", slug="suspension")
        self.product = Product.objects.create(
            name="Coilover Kit",
            slug="coilover-kit",
            sku="BGM-SUSP-1",
            category=self.category,
            price=Decimal("899.00"),
            is_active=True,
        )
        self.checkout_url = reverse("store:store-checkout")

    def test_checkout_reference_photo_syncs_to_client_files(self):
        user = User.objects.create_user(
            username="checkout-client",
            email="checkout.client@example.com",
            password="pass12345",
        )
        self.client.force_login(user)

        session = self.client.session
        session["cart_items"] = {
            "items": [
                {
                    "product_id": self.product.id,
                    "option_id": None,
                    "qty": 1,
                }
            ]
        }
        session.save()

        image_buffer = io.BytesIO()
        Image.new("RGB", (20, 20), color=(200, 60, 20)).save(image_buffer, format="PNG")
        image_buffer.seek(0)
        upload = SimpleUploadedFile(
            "checkout-reference.png",
            image_buffer.read(),
            content_type="image/png",
        )

        response = self.client.post(
            self.checkout_url,
            data={
                "customer_name": "Checkout Client",
                "email": "checkout.client@example.com",
                "phone": "+1 555 123 4567",
                "delivery_method": "pickup",
                "pay_mode": "full",
                "payment_method": "etransfer",
                "agree": "1",
                "reference_image": upload,
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.count(), 1)
        order = Order.objects.first()
        self.assertTrue(bool(order.reference_image))
        self.assertEqual(ClientFile.objects.filter(user=user).count(), 1)

    @patch("store.views.get_checkout_printful_shipping")
    def test_checkout_reference_photo_is_ignored_for_merch(self, shipping_quote):
        # Merch now requires a delivery address and live rate. Stub only the
        # external quote so this still exercises order persistence/upload rules.
        shipping_quote.return_value = {
            "rates": [{"id": "synthetic-standard"}],
            "selected_rate_id": "synthetic-standard",
            "shipping_cost": Decimal("12.00"),
            "shipping_name": "Standard",
            "shipping_currency": "CAD",
            "errors": {}, "error": "", "recipient": {},
        }
        merch_category = Category.objects.create(name="Merch", slug="merch")
        merch_product = Product.objects.create(
            name="BGM Hoodie",
            slug="bgm-hoodie",
            sku="PF-HOODIE-1",
            category=merch_category,
            price=Decimal("85.00"),
            is_active=True,
        )

        user = User.objects.create_user(
            username="checkout-merch-client",
            email="checkout.merch@example.com",
            password="pass12345",
        )
        self.client.force_login(user)

        session = self.client.session
        session["cart_items"] = {
            "items": [
                {
                    "product_id": merch_product.id,
                    "option_id": None,
                    "qty": 1,
                }
            ]
        }
        session.save()

        image_buffer = io.BytesIO()
        Image.new("RGB", (20, 20), color=(20, 120, 200)).save(image_buffer, format="PNG")
        image_buffer.seek(0)
        upload = SimpleUploadedFile(
            "checkout-merch-reference.png",
            image_buffer.read(),
            content_type="image/png",
        )

        response = self.client.post(
            self.checkout_url,
            data={
                "customer_name": "Checkout Merch Client",
                "email": "checkout.merch@example.com",
                "phone": "+1 555 222 3333",
                "delivery_method": "shipping",
                "address_line1": "123 Example St",
                "city": "Calgary",
                "region": "AB",
                "postal_code": "T1T1T1",
                "country": "Canada",
                "printful_shipping_rate_id": "synthetic-standard",
                "pay_mode": "full",
                "payment_method": "etransfer",
                "agree": "1",
                "reference_image": upload,
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.count(), 1)
        order = Order.objects.first()
        self.assertFalse(bool(order.reference_image))
        self.assertEqual(ClientFile.objects.filter(user=user).count(), 0)
