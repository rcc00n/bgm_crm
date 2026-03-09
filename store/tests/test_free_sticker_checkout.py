from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from store.models import Category, Order, Product, ProductOption, StoreShippingSettings


@override_settings(
    ETRANSFER_EMAIL="payments@example.com",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class FreeStickerCheckoutTests(TestCase):
    def setUp(self):
        self.merch_category = Category.objects.create(name="Merch", slug="merch")
        self.checkout_url = reverse("store:store-checkout")
        self.printful_rates_url = reverse("store:store-checkout-printful-rates")
        StoreShippingSettings.objects.create(
            free_shipping_threshold_cad=Decimal("90.00"),
            delivery_cost_under_threshold_cad=Decimal("0.00"),
        )

    def _create_merch_product(self, *, name: str, slug: str, sku: str, price: str) -> Product:
        return Product.objects.create(
            name=name,
            slug=slug,
            sku=sku,
            category=self.merch_category,
            price=Decimal(price),
            is_active=True,
        )

    def _set_cart(self, product: Product):
        session = self.client.session
        session["cart_items"] = {
            "items": [
                {
                    "product_id": product.id,
                    "option_id": None,
                    "qty": 1,
                }
            ]
        }
        session.save()

    def _shipping_quote(self, *, selected_rate_id: str = "pf-standard") -> dict:
        return {
            "rates": [{"id": "pf-standard", "name": "Standard", "rate": "12.00", "currency": "CAD"}],
            "selected_rate_id": selected_rate_id,
            "selected_rate": {"id": "pf-standard", "name": "Standard", "rate": "12.00", "currency": "CAD"},
            "shipping_cost": Decimal("12.00"),
            "shipping_name": "Standard",
            "shipping_currency": "CAD",
            "recipient": {},
            "errors": {},
            "error": "",
        }

    @patch("store.views.get_checkout_printful_shipping")
    def test_free_sticker_picker_hidden_below_threshold(self, get_checkout_printful_shipping):
        get_checkout_printful_shipping.return_value = self._shipping_quote()
        main_product = self._create_merch_product(
            name="BGM Tee",
            slug="bgm-tee",
            sku="PF-TEE-1",
            price="89.00",
        )
        self._create_merch_product(
            name="BGM Bubble-free stickers",
            slug="bgm-bubble-free-stickers",
            sku="PF-STICKER-1",
            price="8.00",
        )
        self._set_cart(main_product)

        response = self.client.get(self.checkout_url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["free_sticker_eligible"])
        self.assertNotContains(response, 'name="free_sticker_choice"', html=False)

    @patch("store.views.get_checkout_printful_shipping")
    def test_free_sticker_picker_shows_at_threshold(self, get_checkout_printful_shipping):
        get_checkout_printful_shipping.return_value = self._shipping_quote()
        main_product = self._create_merch_product(
            name="BGM Hoodie",
            slug="bgm-hoodie",
            sku="PF-HOODIE-1",
            price="90.00",
        )
        sticker = self._create_merch_product(
            name="BGM Bubble-free stickers",
            slug="bgm-bubble-free-stickers",
            sku="PF-STICKER-2",
            price="8.00",
        )
        ProductOption.objects.create(
            product=sticker,
            name="3x3",
            sku="PF-STICKER-2-3X3",
            price=Decimal("8.00"),
            is_active=True,
        )
        ProductOption.objects.create(
            product=sticker,
            name="4x4",
            sku="PF-STICKER-2-4X4",
            price=Decimal("10.00"),
            is_active=True,
            sort_order=1,
        )
        self._set_cart(main_product)

        response = self.client.get(self.checkout_url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["free_sticker_eligible"])
        self.assertEqual(len(response.context["free_sticker_choices"]), 1)
        self.assertContains(response, "Free sticker")
        self.assertContains(response, 'name="free_sticker_choice"', html=False)

    @patch("store.views.get_checkout_printful_shipping")
    def test_selected_free_sticker_is_added_as_zero_dollar_order_item(self, get_checkout_printful_shipping):
        get_checkout_printful_shipping.return_value = self._shipping_quote()
        main_product = self._create_merch_product(
            name="BGM Hoodie",
            slug="bgm-hoodie-order",
            sku="PF-HOODIE-2",
            price="90.00",
        )
        sticker = self._create_merch_product(
            name="BGM Bad Guy Motors sticker",
            slug="bgm-bad-guy-motors-sticker",
            sku="PF-STICKER-3",
            price="6.00",
        )
        small_option = ProductOption.objects.create(
            product=sticker,
            name="3x3",
            sku="PF-STICKER-3-3X3",
            price=Decimal("6.00"),
            is_active=True,
        )
        ProductOption.objects.create(
            product=sticker,
            name="5.5x5.5",
            sku="PF-STICKER-3-5X5",
            price=Decimal("9.00"),
            is_active=True,
            sort_order=1,
        )
        self._set_cart(main_product)
        choice_value = f"{sticker.id}:{small_option.id}"

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
                "printful_shipping_rate_id": "pf-standard",
                "free_sticker_choice": choice_value,
                "agree": "1",
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.items.count(), 2)
        free_sticker_item = order.items.get(product=sticker)
        self.assertEqual(free_sticker_item.qty, 1)
        self.assertEqual(free_sticker_item.option, small_option)
        self.assertEqual(free_sticker_item.price_at_moment, Decimal("0.00"))

    @patch("store.views.get_checkout_printful_shipping")
    def test_live_shipping_quote_receives_selected_free_sticker(self, get_checkout_printful_shipping):
        captured = {}

        def _fake_quote(**kwargs):
            captured["positions"] = kwargs["positions"]
            return self._shipping_quote(selected_rate_id=kwargs.get("selected_rate_id") or "pf-standard")

        get_checkout_printful_shipping.side_effect = _fake_quote
        main_product = self._create_merch_product(
            name="BGM Hoodie",
            slug="bgm-hoodie-rates",
            sku="PF-HOODIE-3",
            price="90.00",
        )
        sticker = self._create_merch_product(
            name="Middle Finger Bubble-free stickers",
            slug="middle-finger-bubble-free-stickers",
            sku="PF-STICKER-4",
            price="8.00",
        )
        small_option = ProductOption.objects.create(
            product=sticker,
            name="3x3",
            sku="PF-STICKER-4-3X3",
            price=Decimal("8.00"),
            is_active=True,
        )
        self._set_cart(main_product)

        response = self.client.post(
            self.printful_rates_url,
            data={
                "customer_name": "Merch Buyer",
                "email": "merch.buyer@example.com",
                "phone": "+1 555 777 8888",
                "address_line1": "123 Main St",
                "city": "Calgary",
                "region": "AB",
                "postal_code": "T1T1T1",
                "country": "Canada",
                "printful_shipping_rate_id": "pf-standard",
                "free_sticker_choice": f"{sticker.id}:{small_option.id}",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(captured["positions"]), 2)
        self.assertEqual(captured["positions"][-1]["product"].id, sticker.id)
        self.assertEqual(captured["positions"][-1]["option"].id, small_option.id)
