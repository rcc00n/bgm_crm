from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from store.models import Category, Order, Product


@override_settings(
    ETRANSFER_EMAIL="payments@example.com",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class CheckoutPaymentModeTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Suspension", slug="suspension")
        self.product = Product.objects.create(
            name="Coilover Kit",
            slug="coilover-kit",
            sku="BGM-SUSP-2",
            category=self.category,
            price=Decimal("899.00"),
            is_active=True,
        )
        self.checkout_url = reverse("store:store-checkout")

    def _set_cart(self):
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

    def test_checkout_ignores_partial_payment_requests(self):
        self._set_cart()

        response = self.client.post(
            self.checkout_url,
            data={
                "customer_name": "Checkout Client",
                "email": "checkout.client@example.com",
                "phone": "+1 555 123 4567",
                "delivery_method": "pickup",
                "pay_mode": "deposit_50",
                "payment_method": "etransfer",
                "agree": "1",
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.payment_mode, Order.PaymentMode.FULL)
        self.assertEqual(order.payment_balance_due, Decimal("975.42"))
