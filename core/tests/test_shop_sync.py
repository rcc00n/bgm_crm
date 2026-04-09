from decimal import Decimal

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import Lead, ServiceLead, ShopSharedDataRecord
from core.services.shop_sync import (
    append_shop_lead,
    get_or_create_shop_record,
    map_shop_product_name,
    normalize_shop_payload,
    sync_order_to_shop,
)
from store.models import Category, Order, OrderItem, Product


class ShopSyncServiceTests(TestCase):
    def test_append_shop_lead_preserves_existing_arrays(self):
        record = get_or_create_shop_record()
        record.payload = {
            "jobs": [{"id": 1}],
            "leads": [],
            "designs": [{"id": 2}],
        }
        record.save(update_fields=["payload", "updated_at"])

        record, lead = append_shop_lead(
            {
                "name": "Jane Doe",
                "contact": "jane@example.com",
                "product": "Outlaw Series Front",
                "notes": "Website order",
                "value": "1250.50",
            }
        )

        self.assertEqual(record.payload["jobs"], [{"id": 1}])
        self.assertEqual(record.payload["designs"], [{"id": 2}])
        self.assertEqual(len(record.payload["leads"]), 1)
        self.assertEqual(lead["product"], "Outlaw Bumper")
        self.assertEqual(lead["value"], 1250.5)

    def test_sync_order_uses_custom_build_for_mixed_products(self):
        category = Category.objects.create(name="Fabrication", slug="fabrication")
        outlaw = Product.objects.create(
            name="Outlaw Series Front Bumper",
            slug="outlaw-series-front-bumper",
            sku="OUTLAW-1",
            category=category,
            price=Decimal("1000.00"),
        )
        mudflap = Product.objects.create(
            name="Premium Mudflap Set",
            slug="premium-mudflap-set",
            sku="MUDFLAP-1",
            category=category,
            price=Decimal("250.00"),
        )
        order = Order.objects.create(
            customer_name="John Doe",
            email="john@example.com",
            phone="4035551212",
            vehicle_year=2021,
            vehicle_make="Ford",
            vehicle_model="F-350",
            notes="Needs rush delivery",
            payment_amount=Decimal("1250.00"),
            payment_balance_due=Decimal("0.00"),
        )
        OrderItem.objects.create(order=order, product=outlaw, qty=1)
        OrderItem.objects.create(order=order, product=mudflap, qty=1)

        lead = sync_order_to_shop(order.pk)

        self.assertEqual(lead["product"], "Custom Build")
        self.assertIn("Vehicle: 2021 Ford F-350", lead["notes"])
        self.assertIn("Outlaw Series Front Bumper", lead["notes"])
        self.assertIn("Premium Mudflap Set", lead["notes"])

    def test_product_name_mapping_uses_exact_allowed_values(self):
        self.assertEqual(map_shop_product_name("Badland rock sliders"), "Badland Bars / Rock Sliders")
        self.assertEqual(map_shop_product_name("running boards"), "Running Boards")
        self.assertEqual(map_shop_product_name("unknown"), "Custom Build")


@override_settings(
    SHOP_API_TOKEN="test-token",
    SHOP_API_ALLOWED_ORIGINS=["https://shop.example.com"],
)
class ShopSyncApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.headers = {
            "HTTP_AUTHORIZATION": "Bearer test-token",
            "HTTP_ORIGIN": "https://shop.example.com",
        }

    def test_get_endpoint_returns_normalized_payload(self):
        response = self.client.get(
            reverse("shop-shared-data-api", args=["bgm-shop-data-v3"]),
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], normalize_shop_payload({}))
        self.assertEqual(response["Access-Control-Allow-Origin"], "https://shop.example.com")

    def test_put_endpoint_replaces_payload(self):
        response = self.client.put(
            reverse("shop-shared-data-api", args=["bgm-shop-data-v3"]),
            data='{"value":{"jobs":[{"id":1}],"leads":[],"designs":[]}}',
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"]["jobs"], [{"id": 1}])
        record = ShopSharedDataRecord.objects.get(key="bgm-shop-data-v3")
        self.assertEqual(record.payload["jobs"], [{"id": 1}])

    def test_webhook_endpoint_appends_lead(self):
        response = self.client.post(
            reverse("shop-website-lead-webhook"),
            data='{"name":"Jane Doe","contact":"jane@example.com","product":"Flat deck quote","notes":"Customer asked for install"}',
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["lead"]["product"], "Flat Deck")
        self.assertEqual(len(payload["document"]["value"]["leads"]), 1)

    def test_api_rejects_missing_token(self):
        response = self.client.get(reverse("shop-shared-data-api", args=["bgm-shop-data-v3"]))
        self.assertEqual(response.status_code, 401)
