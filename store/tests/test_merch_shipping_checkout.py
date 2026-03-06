from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from store.models import Category, Order, Product, StoreShippingSettings


@override_settings(
    ETRANSFER_EMAIL="payments@example.com",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class MerchShippingCheckoutTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Merch", slug="merch")
        self.product = Product.objects.create(
            name="BGM Tee",
            slug="bgm-tee",
            sku="PF-TEE-1",
            category=self.category,
            price=Decimal("100.00"),
            is_active=True,
        )
        StoreShippingSettings.objects.create(
            free_shipping_threshold_cad=Decimal("200.00"),
            delivery_cost_under_threshold_cad=Decimal("15.00"),
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

    def test_merch_checkout_shows_single_shipping_line_and_expected_total(self):
        self._set_cart()

        response = self.client.get(self.checkout_url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["cart_is_merch_checkout"])
        self.assertEqual(response.context["shipping_cost"], Decimal("15.00"))
        self.assertEqual(response.context["order_subtotal"], Decimal("115.00"))
        self.assertEqual(response.context["order_total_with_fees"], Decimal("124.78"))

        html = response.content.decode("utf-8")
        self.assertEqual(html.count('id="orderShippingRow"'), 1)
        self.assertEqual(html.count('id="orderShipping"'), 1)

    def test_merch_checkout_persists_single_shipping_charge_on_order(self):
        self._set_cart()

        response = self.client.post(
            self.checkout_url,
            data={
                "customer_name": "Merch Buyer",
                "email": "merch.buyer@example.com",
                "phone": "+1 555 777 8888",
                "delivery_method": "shipping",
                "address_line1": "123 Main St",
                "city": "Calgary",
                "region": "AB",
                "postal_code": "T1T1T1",
                "country": "Canada",
                "pay_mode": "full",
                "payment_method": "etransfer",
                "agree": "1",
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.count(), 1)

        order = Order.objects.get()
        self.assertEqual(order.shipping_cost, Decimal("15.00"))
        self.assertEqual(order.total, Decimal("115.00"))
