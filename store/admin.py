from django.contrib import admin
from django.utils.html import format_html

from .models import (
    CarMake,
    CarModel,
    Category,
    Product,
    ProductImage,
    Order,
    OrderItem,
)
from .forms_store import ProductAdminForm


# ─────────────────────────── Auto directories ───────────────────────────

@admin.register(CarMake)
class CarMakeAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


@admin.register(CarModel)
class CarModelAdmin(admin.ModelAdmin):
    list_display = ["make", "name", "year_from", "year_to"]
    list_filter = ["make"]
    search_fields = ["name", "make__name"]


# ───────────────────────────── Categories / Products ─────────────────────────────

class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "image_preview")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    fields = ("name", "slug", "description", "image", "image_preview")
    readonly_fields = ("image_preview",)

    def image_preview(self, obj):
        if getattr(obj, "image", None):
            try:
                return format_html(
                    '<img src="{}" style="max-width:180px; border-radius:8px;" />',
                    obj.image.url,
                )
            except Exception:
                return "—"
        return "—"

    image_preview.short_description = "Preview"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """
    Product admin with:
    - human-friendly specs editor (text -> JSON) via ProductAdminForm
    - HTML preview for saved specs
    - gallery inline
    """
    form = ProductAdminForm
    list_display = ("name", "sku", "category", "price", "currency", "inventory", "is_active")
    list_filter = ("is_active", "category", "currency")
    search_fields = ("name", "sku", "description")
    prepopulated_fields = {"slug": ("name",)}
    list_select_related = ("category",)
    inlines = [ProductImageInline]
    filter_horizontal = ("compatible_models",)
    readonly_fields = ("created_at", "updated_at", "specs_preview")

    # Use explicit fields layout: text specs + HTML preview (read-only)
    fields = (
        "name", "slug", "sku", "category",
        "price", "currency", "inventory", "is_active",
        "main_image",
        "short_description", "description",
        "compatible_models",
        "specs_text", "specs_preview",
        "created_at", "updated_at",
    )

    def specs_preview(self, obj):
        """Pretty HTML preview for stored JSON specs."""
        if not getattr(obj, "specs", None):
            return "—"
        rows = []
        for k, v in obj.specs.items():
            if isinstance(v, (list, tuple)):
                vv = ", ".join(str(x) for x in v)
            elif isinstance(v, dict):
                vv = "; ".join(f"{kk}: {vv}" for kk, vv in v.items())
            else:
                vv = str(v)
            rows.append(
                "<tr>"
                f"<th style='text-align:left;padding:.25rem .6rem;white-space:nowrap'>{k}</th>"
                f"<td style='padding:.25rem .6rem;color:#eaeaea'>{vv}</td>"
                "</tr>"
            )
        html = (
            "<table style='width:100%;border-collapse:collapse;"
            "background:rgba(255,255,255,.03);border-radius:8px'>"
            + "".join(rows) +
            "</table>"
        )
        return format_html(html)

    specs_preview.short_description = "Specifications (preview)"


# ──────────────────────────────── Orders ────────────────────────────────

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "customer_name", "status", "total")
    list_filter = ("status", "created_at")
    search_fields = ("customer_name", "email", "phone")
    inlines = [OrderItemInline]
