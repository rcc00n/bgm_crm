# store/views.py
from decimal import Decimal
from typing import Dict, Iterable

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Category, Order, OrderItem, Product

# ────────────────────────── Публичные страницы ──────────────────────────

def store_home(request):
    categories = Category.objects.annotate(product_count=Count("products")).order_by("name")
    products = (
        Product.objects.filter(is_active=True)
        .select_related("category")
        .order_by("-created_at")[:12]
    )
    return render(request, "store/store_home.html", {"categories": categories, "products": products})


def category_list(request, slug: str):
    category = get_object_or_404(Category, slug=slug)
    products = (
        Product.objects.filter(is_active=True, category=category)
        .select_related("category")
        .order_by("name")
    )
    return render(request, "store/category_list.html", {"category": category, "products": products})


def product_detail(request, slug: str):
    product = get_object_or_404(Product.objects.select_related("category"), slug=slug, is_active=True)
    related = (
        Product.objects.filter(is_active=True, category=product.category)
        .exclude(pk=product.pk)
        .order_by("-created_at")[:8]
    )
    return render(request, "store/product_detail.html", {"product": product, "related": related})


# ──────────────────────────── Корзина (сессии) ───────────────────────────

CART_KEY = "cart_items"  # {product_id: qty}

def _cart(session) -> Dict[str, int]:
    return session.setdefault(CART_KEY, {})

@require_POST
def cart_add(request, slug: str):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    try:
        qty = int(request.POST.get("qty", 1))
    except (TypeError, ValueError):
        qty = 1
    qty = max(1, qty)

    cart = _cart(request.session)
    pid = str(product.id)
    cart[pid] = cart.get(pid, 0) + qty
    request.session.modified = True

    if request.POST.get("buy_now") == "1":
        messages.success(request, f"Товар «{product.name}» добавлен. Переходим к оформлению.")
        return redirect("store:store-checkout")

    messages.success(request, f"Добавлено в корзину: «{product.name}».")
    return redirect("store:store-product", slug=product.slug)


def cart_view(request):
    cart = _cart(request.session)
    ids = list(map(int, cart.keys())) if cart else []
    items = Product.objects.filter(id__in=ids).select_related("category")

    positions, total = [], Decimal("0.00")
    for p in items:
        qty = int(cart.get(str(p.id), 0))
        unit = Decimal(str(p.price))
        line_total = unit * qty
        total += line_total
        positions.append({"product": p, "qty": qty, "line_total": line_total})
    return render(request, "store/cart.html", {"positions": positions, "total": total})


@require_POST
def cart_remove(request, slug: str):
    product = get_object_or_404(Product, slug=slug)
    cart = _cart(request.session)
    pid = str(product.id)
    if pid in cart:
        cart.pop(pid)
        request.session.modified = True
        messages.info(request, f"Товар «{product.name}» удалён из корзины.")
    return redirect("store:store-cart")


# ─────────────────────────────── Вспомогалки ─────────────────────────────

def _model_field_names(model) -> set:
    names = set()
    for f in model._meta.get_fields():
        if getattr(f, "concrete", False) and not getattr(f, "many_to_many", False) and not getattr(f, "one_to_many", False):
            names.add(f.name)
    return names

def _first_present(model_fields: set, candidates: Iterable[str]):
    for name in candidates:
        if name in model_fields:
            return name
    return None


# ─────────────────────────────── Checkout ────────────────────────────────

def checkout(request):
    # собрать позиции заказа из корзины
    cart = _cart(request.session)
    ids = list(map(int, cart.keys())) if cart else []
    qs = Product.objects.filter(id__in=ids).select_related("category")

    positions, total = [], Decimal("0.00")
    for p in qs:
        qty = int(cart.get(str(p.id), 0))
        unit = Decimal(str(p.price))
        line_total = unit * qty
        total += line_total
        positions.append({"product": p, "qty": qty, "line_total": line_total})

    if request.method == "POST" and not positions:
        messages.error(request, "Корзина пуста.")
        return redirect("store:store-cart")

    form = {"delivery_method": "shipping"}
    errors: Dict[str, str] = {}

    if request.method == "POST":
        def val(name, default=""):
            return (request.POST.get(name) or default).strip()

        form = {
            "customer_name": val("customer_name"),
            "email": val("email"),
            "phone": val("phone"),
            "delivery_method": val("delivery_method", "shipping"),
            "address_line1": val("address_line1"),
            "address_line2": val("address_line2"),
            "city": val("city"),
            "region": val("region"),
            "postal_code": val("postal_code"),
            "country": val("country") or "Canada",
            "pickup_notes": val("pickup_notes"),
            "comment": val("comment"),
            "agree": request.POST.get("agree") == "1",
        }

        # валидация
        if not form["customer_name"]:
            errors["customer_name"] = "Укажите имя и фамилию."
        if not form["phone"]:
            errors["phone"] = "Укажите телефон."
        try:
            validate_email(form["email"])
        except ValidationError:
            errors["email"] = "Неверный формат email."

        is_pickup = form["delivery_method"] == "pickup"
        if not is_pickup:
            if not form["address_line1"]:
                errors["address_line1"] = "Улица и дом обязательны."
            if not form["city"]:
                errors["city"] = "Укажите город."
            if not form["region"]:
                errors["region"] = "Укажите регион/штат."
            if not form["postal_code"]:
                errors["postal_code"] = "Укажите индекс."
            if not form["country"]:
                errors["country"] = "Укажите страну."

        if not form["agree"]:
            errors["agree"] = "Нужно подтвердить согласие с условиями."

        if not errors:
            o_fields = _model_field_names(Order)

            order_kwargs = {}
            for key in ["customer_name", "email", "phone"]:
                if key in o_fields:
                    order_kwargs[key] = form[key]

            if "total" in o_fields:
                order_kwargs["total"] = total

            name = _first_present(o_fields, ["delivery_method", "shipping_method"])
            if name:
                order_kwargs[name] = form["delivery_method"]

            mapping = {
                "address_line1": ["address_line1", "address1", "shipping_address1", "address", "shipping_address"],
                "address_line2": ["address_line2", "address2", "shipping_address2"],
                "city": ["city", "shipping_city"],
                "region": ["region", "state", "province", "shipping_region", "shipping_state", "shipping_province"],
                "postal_code": ["postal_code", "zip_code", "zip", "postcode"],
                "country": ["country", "shipping_country"],
            }
            for src, cands in mapping.items():
                dst = _first_present(o_fields, cands)
                if dst and form[src]:
                    order_kwargs[dst] = form[src]

            comment_field = _first_present(o_fields, ["comment", "comments", "notes", "note", "customer_note", "customer_notes"])
            if comment_field:
                extra_blocks = []
                if form["comment"]:
                    extra_blocks.append(form["comment"])
                if is_pickup and form["pickup_notes"]:
                    extra_blocks.append(f"[Самовывоз] {form['pickup_notes']}")
                if not is_pickup:
                    addr_pushed = all(
                        _first_present(o_fields, mapping[k]) for k in ["address_line1", "city", "region", "postal_code", "country"]
                    )
                    if not addr_pushed:
                        addr_text = ", ".join(
                            [form["address_line1"], form["address_line2"], form["city"], form["region"], form["postal_code"], form["country"]]
                        ).strip(", ").replace("  ", " ")
                        extra_blocks.append(f"[Доставка] {addr_text}")
                if extra_blocks:
                    order_kwargs[comment_field] = "\n".join(extra_blocks)

            with transaction.atomic():
                order = Order.objects.create(**order_kwargs)

                # ── создание позиций ──
                i_fields = _model_field_names(OrderItem)

                product_field = _first_present(i_fields, ["product", "item", "sku_product"])
                qty_field     = _first_present(i_fields, ["quantity", "qty", "count", "amount", "quantity_ordered"])
                price_field   = _first_present(i_fields, ["price_at_moment", "unit_price", "price", "unit", "price_snapshot"])
                line_field    = _first_present(i_fields, ["total", "line_total", "subtotal", "line_price", "price_total"])
                currency_field= _first_present(i_fields, ["currency", "currency_code"])

                for it in positions:
                    p = it["product"]
                    qty = int(it["qty"])
                    unit = Decimal(str(p.price))
                    line_total = unit * qty

                    kwargs = {"order": order}
                    if product_field:
                        kwargs[product_field] = p
                    if qty_field:
                        kwargs[qty_field] = qty
                    if price_field:
                        kwargs[price_field] = unit  # важно: NOT NULL
                    if line_field:
                        kwargs[line_field] = line_total
                    if currency_field:
                        kwargs[currency_field] = getattr(p, "currency", "USD")

                    OrderItem.objects.create(**kwargs)

                # очистить корзину
                request.session[CART_KEY] = {}
                request.session.modified = True

            messages.success(request, f"Заказ успешно создан. Спасибо! Номер: #{order.id}")
            return redirect("store:store")

    return render(
        request,
        "store/checkout.html",
        {
            "positions": positions,
            "total": total,
            "form": form,
            "errors": errors,
        },
    )
