import json
import uuid
from decimal import Decimal

from django.core.management.base import BaseCommand

from store.models import Category, Order, OrderItem, Product


class Command(BaseCommand):
    help = "Create a temporary order item and verify that product inventory is decremented."

    def add_arguments(self, parser):
        parser.add_argument("--inventory", type=int, default=5, help="Starting inventory for the temporary product.")
        parser.add_argument("--qty", type=int, default=2, help="Quantity for the temporary order item.")

    def handle(self, *args, **options):
        start_inventory = max(0, int(options["inventory"] or 0))
        qty = max(1, int(options["qty"] or 1))
        token = uuid.uuid4().hex[:8]

        category = None
        product = None
        order = None
        order_item = None

        try:
            category = Category.objects.create(
                name=f"TMP Inventory {token}",
                slug=f"tmp-inventory-{token}",
            )
            product = Product.objects.create(
                name=f"TMP Product {token}",
                slug=f"tmp-product-{token}",
                sku=f"TMP-INV-{token.upper()}",
                category=category,
                price=Decimal("9.99"),
                inventory=start_inventory,
                is_active=False,
            )
            order = Order.objects.create(
                customer_name="Inventory Probe",
                email=f"inventory-probe-{token}@example.com",
                phone="555-0100",
                delivery_method="pickup",
                payment_status=Order.PaymentStatus.UNPAID,
                payment_mode=Order.PaymentMode.FULL,
            )
            before = product.inventory
            order_item = OrderItem.objects.create(order=order, product=product, qty=qty)
            product.refresh_from_db()
            after = product.inventory
            deducted = before - after
            self.stdout.write(
                json.dumps(
                    {
                        "before": before,
                        "after": after,
                        "deducted": deducted,
                        "requested_qty": qty,
                    }
                )
            )
        finally:
            if order_item is not None:
                order_item.delete()
            if order is not None:
                order.delete()
            if product is not None:
                product.delete()
            if category is not None:
                category.delete()
