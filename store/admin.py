# store/admin.py
from django.contrib import admin
from django.utils.html import format_html

from .models import (
    CarMake,
    CarModel,
    Category,
    Product,
    ProductImage,
    ProductOption,
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

class ProductOptionInline(admin.TabularInline):
    model = ProductOption
    extra = 1
    fields = ("name", "description", "is_active", "sort_order")
    ordering = ("sort_order", "id")


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
    Product admin:
    - specs_text (из формы) -> JSON в поле specs
    - HTML preview для specs
    - галерея через inline
    """
    form = ProductAdminForm
    list_display = ("name", "sku", "category", "price", "currency", "inventory", "is_active")
    list_filter = ("is_active", "category", "currency")
    search_fields = ("name", "sku", "description")
    prepopulated_fields = {"slug": ("name",)}
    list_select_related = ("category",)
    inlines = [ProductOptionInline, ProductImageInline]
    filter_horizontal = ("compatible_models",)
    readonly_fields = ("created_at", "updated_at", "specs_preview")

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
        """Pretty HTML preview for JSON specs."""
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


@admin.register(ProductOption)
class ProductOptionAdmin(admin.ModelAdmin):
    list_display = ("name", "product", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name", "product__name", "product__sku")
    autocomplete_fields = ("product",)
    ordering = ("product__name", "sort_order", "id")


# ──────────────────────────────── Orders ────────────────────────────────

class StatusBadgeMixin:
    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        label = getattr(obj, "status_label", getattr(obj, "get_status_display", lambda: obj.status)())
        color = getattr(obj, "status_color", "#999")
        return format_html(
            "<span style='display:inline-block;padding:.18rem .55rem;border-radius:999px;"
            "font-weight:700;font-size:.85rem;color:#fff;background:{}'>{}</span>",
            color, label
        )


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    autocomplete_fields = ["product", "option"]
    fields = ("product", "option", "qty", "price_at_moment", "subtotal")
    readonly_fields = ("subtotal",)


@admin.register(Order)
class OrderAdmin(StatusBadgeMixin, admin.ModelAdmin):
    # безопасный показ «даты создания» — если поля нет, покажем «—»
    @admin.display(description="Created")
    def created_display(self, obj):
        for attr in ("created_at", "created", "created_on", "timestamp"):
            if hasattr(obj, attr):
                val = getattr(obj, attr)
                return val if val else "—"
        return "—"
    
    change_list_template = "admin/store/order/change_list.html"
    list_display = ("id", "created_display", "customer_name", "status_badge", "status", "total")
    list_display_links = ("id", "customer_name")
    list_editable = ("status",)  # редактирование статуса прямо в списке

    # убрали created_at из фильтров/иерархии, т.к. поле не гарантировано
    list_filter = ("status",)
    search_fields = ("customer_name", "email", "phone", "id")
    ordering = ("-id",)  # вместо date_hierarchy
    inlines = [OrderItemInline]
    readonly_fields = ("shipped_at", "completed_at", "cancelled_at")

    actions = ("mark_processing", "mark_shipped", "mark_completed", "mark_cancelled")

    def _bulk_set(self, request, queryset, status):
        updated = 0
        for o in queryset:
            o.set_status(status, save=True)
            updated += 1
        self.message_user(request, f"Orders updated: {updated}")

    def mark_processing(self, request, qs): self._bulk_set(request, qs, Order.STATUS_PROCESSING)
    def mark_shipped(self, request, qs):    self._bulk_set(request, qs, Order.STATUS_SHIPPED)
    def mark_completed(self, request, qs):  self._bulk_set(request, qs, Order.STATUS_COMPLETED)
    def mark_cancelled(self, request, qs):  self._bulk_set(request, qs, Order.STATUS_CANCELLED)

    mark_processing.short_description = "Mark as processing"
    mark_shipped.short_description    = "Mark as shipped"
    mark_completed.short_description  = "Mark as completed"
    mark_cancelled.short_description  = "Mark as cancelled"
