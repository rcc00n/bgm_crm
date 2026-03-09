from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from store.models import Category, Order, Product, StoreInventorySettings


@override_settings(
    ETRANSFER_EMAIL="payments@example.com",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class InventoryControlsTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Exhaust", slug="exhaust")
        self.product = Product.objects.create(
            name="Turbo Back Exhaust",
            slug="turbo-back-exhaust",
            sku="BGM-EXH-1",
            category=self.category,
            price=Decimal("799.00"),
            inventory=0,
            is_active=True,
        )
        self.detail_url = reverse("store:store-product", kwargs={"slug": self.product.slug})
        self.add_url = reverse("store:store-cart-add", kwargs={"slug": self.product.slug})
        self.checkout_url = reverse("store:store-checkout")

    def _set_cart(self, qty=1):
        session = self.client.session
        session["cart_items"] = {
            "items": [
                {
                    "product_id": self.product.id,
                    "option_id": None,
                    "qty": qty,
                }
            ]
        }
        session.save()

    def test_product_detail_shows_out_of_stock_notice_when_blocked(self):
        StoreInventorySettings.objects.create(low_stock_threshold=5, allow_out_of_stock_orders=False)

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Out of stock right now")
        self.assertContains(response, "Out of stock")

    def test_cart_add_is_blocked_when_out_of_stock_orders_disabled(self):
        StoreInventorySettings.objects.create(low_stock_threshold=5, allow_out_of_stock_orders=False)

        response = self.client.post(self.add_url, data={"qty": "1"}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "is out of stock right now")
        cart_items = (self.client.session.get("cart_items") or {}).get("items") or []
        self.assertEqual(cart_items, [])

    def test_cart_add_is_blocked_when_requested_qty_exceeds_inventory(self):
        StoreInventorySettings.objects.create(low_stock_threshold=5, allow_out_of_stock_orders=False)
        self.product.inventory = 2
        self.product.save(update_fields=["inventory"])

        response = self.client.post(self.add_url, data={"qty": "3"}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Only 2 left for "Turbo Back Exhaust".')
        cart_items = (self.client.session.get("cart_items") or {}).get("items") or []
        self.assertEqual(cart_items, [])

    def test_checkout_blocks_out_of_stock_cart_items(self):
        StoreInventorySettings.objects.create(low_stock_threshold=5, allow_out_of_stock_orders=False)
        self._set_cart(qty=1)

        response = self.client.post(
            self.checkout_url,
            data={
                "customer_name": "Inventory Client",
                "email": "inventory.client@example.com",
                "phone": "+1 555 123 4567",
                "delivery_method": "pickup",
                "payment_method": "etransfer",
                "agree": "1",
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inventory updated")
        self.assertEqual(Order.objects.count(), 0)

    def test_order_item_creation_decrements_inventory_when_positive(self):
        self.product.inventory = 4
        self.product.save(update_fields=["inventory"])

        self._set_cart(qty=2)
        response = self.client.post(
            self.checkout_url,
            data={
                "customer_name": "Inventory Client",
                "email": "inventory.client@example.com",
                "phone": "+1 555 123 4567",
                "delivery_method": "pickup",
                "payment_method": "etransfer",
                "agree": "1",
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.inventory, 2)
        self.assertEqual(Order.objects.count(), 1)


class InventoryAdminTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass12345",
        )
        self.client.force_login(self.superuser)
        category = Category.objects.create(name="Tuners", slug="tuners")
        Product.objects.create(
            name="Low Stock Tuner",
            slug="low-stock-tuner",
            sku="BGM-TUNE-LOW",
            category=category,
            price=Decimal("499.00"),
            inventory=2,
            is_active=True,
        )
        Product.objects.create(
            name="Out Tuner",
            slug="out-tuner",
            sku="BGM-TUNE-OUT",
            category=category,
            price=Decimal("599.00"),
            inventory=0,
            is_active=True,
        )
        Product.objects.create(
            name="Healthy Tuner",
            slug="healthy-tuner",
            sku="BGM-TUNE-OK",
            category=category,
            price=Decimal("699.00"),
            inventory=12,
            is_active=True,
        )
        StoreInventorySettings.objects.create(low_stock_threshold=3, allow_out_of_stock_orders=False)
        self.changelist_url = reverse("admin:store_product_changelist")
        self.settings_url = reverse("admin:store_product_inventory_settings")

    def test_product_admin_changelist_shows_inventory_watch_panel(self):
        response = self.client.get(self.changelist_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inventory watch")
        self.assertContains(response, "Low Stock Tuner")
        self.assertContains(response, "Out Tuner")
        self.assertContains(response, "Save inventory rules")

    def test_product_admin_inventory_settings_post_updates_singleton(self):
        response = self.client.post(
            self.settings_url,
            data={
                "low_stock_threshold": "7",
                "allow_out_of_stock_orders": "on",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        settings_obj = StoreInventorySettings.objects.get()
        self.assertEqual(settings_obj.low_stock_threshold, 7)
        self.assertTrue(settings_obj.allow_out_of_stock_orders)
        self.assertContains(response, "Inventory settings updated")
