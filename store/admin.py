# store/admin.py
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

# ─────────────────────────── Справочники авто ───────────────────────────

@admin.register(CarMake)
class CarMakeAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


@admin.register(CarModel)
class CarModelAdmin(admin.ModelAdmin):
    list_display = ["make", "name", "year_from", "year_to"]
    list_filter = ["make"]
    search_fields = ["name", "make__name"]

# ───────────────────────────── Категории/Товары ─────────────────────────────

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
    list_display = (
        "name",
        "sku",
        "category",
        "price",
        "currency",
        "inventory",
        "is_active",
    )
    list_filter = ("is_active", "category", "currency")
    search_fields = ("name", "sku", "description")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProductImageInline]
    # если в модели есть M2M совместимых моделей — оставляем, иначе можно закомментировать
    filter_horizontal = ("compatible_models",)
    readonly_fields = ("created_at", "updated_at")

# ──────────────────────────────── Заказы ────────────────────────────────

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "customer_name", "status", "total")
    list_filter = ("status", "created_at")
    search_fields = ("customer_name", "email", "phone")
    inlines = [OrderItemInline]
