import io
from decimal import Decimal

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
