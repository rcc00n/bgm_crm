import io
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from core.models import ClientFile
from store.models import Category, Product


class CartReferencePhotoTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Lighting", slug="lighting")
        self.product = Product.objects.create(
            name="Aux Light Bar",
            slug="aux-light-bar",
            sku="BGM-LIGHT-1",
            category=self.category,
            price=Decimal("299.00"),
            is_active=True,
        )
        self.add_url = reverse("store:store-cart-add", kwargs={"slug": self.product.slug})
        self.cart_url = reverse("store:store-cart")

    def test_reference_photo_is_marked_in_cart_and_synced_to_client_files(self):
        user = User.objects.create_user(
            username="cart-client",
            email="cart.client@example.com",
            password="pass12345",
        )
        self.client.force_login(user)

        image_buffer = io.BytesIO()
        Image.new("RGB", (16, 16), color=(25, 110, 220)).save(image_buffer, format="PNG")
        image_buffer.seek(0)
        upload = SimpleUploadedFile(
            "cart-reference.png",
            image_buffer.read(),
            content_type="image/png",
        )

        response = self.client.post(
            self.add_url,
            data={"qty": "1", "reference_image": upload},
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ClientFile.objects.filter(user=user).count(), 1)

        cart_items = (self.client.session.get("cart_items") or {}).get("items") or []
        self.assertEqual(len(cart_items), 1)
        self.assertTrue(cart_items[0].get("reference_client_file_id"))

        cart_response = self.client.get(self.cart_url)
        self.assertEqual(cart_response.status_code, 200)
        self.assertContains(cart_response, "Reference photo attached")
