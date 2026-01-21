# store/admin.py
import os

from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils import timezone

from .models import (
    CarMake,
    CarModel,
    Category,
    CleanupBatch,
    ImportBatch,
    StorePricingSettings,
    Product,
    ProductImage,
    ProductOption,
    Order,
    OrderItem,
    CustomFitmentRequest,
)
from .forms_store import ProductAdminForm, ProductImportForm
from .importers import import_products


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

class CleanupStatusFilter(admin.SimpleListFilter):
    title = "Cleanup"
    parameter_name = "cleanup"

    def lookups(self, request, model_admin):
        return (
            ("cleaned", "Cleaned junk"),
            ("all", "All (including cleaned)"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "all":
            return queryset
        if value == "cleaned":
            return queryset.filter(cleanup_batch__isnull=False)
        return queryset.filter(cleanup_batch__isnull=True)


class ProductOptionInline(admin.TabularInline):
    model = ProductOption
    extra = 1
    fields = ("name", "sku", "description", "price", "is_active", "sort_order")
    ordering = ("sort_order", "id")


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


@admin.register(StorePricingSettings)
class StorePricingSettingsAdmin(admin.ModelAdmin):
    list_display = ("price_multiplier_percent", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "Global price multiplier",
            {
                "description": (
                    "Sets one multiplier for all store product and option prices "
                    "(except in-house products). "
                    "100 = no change, 110 = +10%. Use whole percents."
                ),
                "fields": ("price_multiplier_percent",),
            },
        ),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        if StorePricingSettings.objects.exists():
            return False
        return super().has_add_permission(request)


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
    change_list_template = "admin/store/product/change_list.html"
    list_display = (
        "name",
        "sku",
        "category_short",
        "price",
        "currency",
        "inventory",
        "is_in_house",
        "is_active",
        "contact_for_estimate",
    )
    list_editable = ("is_active",)
    list_filter = (
        "is_active",
        "is_in_house",
        "category",
        "currency",
        "contact_for_estimate",
        CleanupStatusFilter,
    )
    search_fields = ("name", "sku", "description")
    prepopulated_fields = {"slug": ("name",)}
    list_select_related = ("category",)
    inlines = [ProductOptionInline, ProductImageInline]
    filter_horizontal = ("compatible_models",)
    readonly_fields = ("created_at", "updated_at", "specs_preview")

    fields = (
        "name", "slug", "sku", "category",
        ("price", "contact_for_estimate"),
        "is_in_house",
        "estimate_from_price",
        "currency", "inventory", "is_active",
        "main_image",
        "short_description", "description",
        "compatible_models", "compatibility",
        "specs_text", "specs_preview",
        "created_at", "updated_at",
    )

    def get_urls(self):
        urls = super().get_urls()
        opts = self.model._meta
        custom_urls = [
            path(
                "import/",
                self.admin_site.admin_view(self.import_view),
                name=f"{opts.app_label}_{opts.model_name}_import",
            ),
            path(
                "rollback-last-import/",
                self.admin_site.admin_view(self.rollback_last_import_view),
                name=f"{opts.app_label}_{opts.model_name}_rollback_last_import",
            ),
            path(
                "cleanup-junk/",
                self.admin_site.admin_view(self.cleanup_junk_view),
                name=f"{opts.app_label}_{opts.model_name}_cleanup_junk",
            ),
            path(
                "rollback-last-cleanup/",
                self.admin_site.admin_view(self.rollback_last_cleanup_view),
                name=f"{opts.app_label}_{opts.model_name}_rollback_last_cleanup",
            ),
            path(
                "autofill-missing-photos/",
                self.admin_site.admin_view(self.autofill_missing_photos_view),
                name=f"{opts.app_label}_{opts.model_name}_autofill_missing_photos",
            ),
            path(
                "autofill-placeholder-photos/",
                self.admin_site.admin_view(self.autofill_placeholder_photos_view),
                name=f"{opts.app_label}_{opts.model_name}_autofill_placeholder_photos",
            ),
            path(
                "rollback-autofill-photos/",
                self.admin_site.admin_view(self.rollback_autofill_photos_view),
                name=f"{opts.app_label}_{opts.model_name}_rollback_autofill_photos",
            ),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        opts = self.model._meta
        last_import = ImportBatch.objects.filter(
            is_dry_run=False,
            rolled_back_at__isnull=True,
        ).order_by("-created_at").first()
        last_cleanup = CleanupBatch.objects.filter(
            rolled_back_at__isnull=True,
        ).order_by("-created_at").first()
        try:
            extra_context["import_url"] = reverse(
                f"admin:{opts.app_label}_{opts.model_name}_import"
            )
        except Exception:
            extra_context["import_url"] = None
        try:
            extra_context["rollback_url"] = reverse(
                f"admin:{opts.app_label}_{opts.model_name}_rollback_last_import"
            )
        except Exception:
            extra_context["rollback_url"] = None
        try:
            extra_context["cleanup_url"] = reverse(
                f"admin:{opts.app_label}_{opts.model_name}_cleanup_junk"
            )
        except Exception:
            extra_context["cleanup_url"] = None
        try:
            extra_context["cleanup_rollback_url"] = reverse(
                f"admin:{opts.app_label}_{opts.model_name}_rollback_last_cleanup"
            )
        except Exception:
            extra_context["cleanup_rollback_url"] = None
        try:
            extra_context["autofill_photos_url"] = reverse(
                f"admin:{opts.app_label}_{opts.model_name}_autofill_missing_photos"
            )
        except Exception:
            extra_context["autofill_photos_url"] = None
        try:
            extra_context["placeholder_photos_url"] = reverse(
                f"admin:{opts.app_label}_{opts.model_name}_autofill_placeholder_photos"
            )
        except Exception:
            extra_context["placeholder_photos_url"] = None
        try:
            extra_context["autofill_rollback_url"] = reverse(
                f"admin:{opts.app_label}_{opts.model_name}_rollback_autofill_photos"
            )
        except Exception:
            extra_context["autofill_rollback_url"] = None
        extra_context["last_import"] = last_import
        extra_context["last_cleanup"] = last_cleanup
        return super().changelist_view(request, extra_context=extra_context)

    def import_view(self, request):
        if not self.has_add_permission(request):
            raise PermissionDenied

        if request.method == "POST":
            form = ProductImportForm(request.POST, request.FILES)
            if form.is_valid():
                import_batch = None
                if not form.cleaned_data["dry_run"]:
                    import_batch = ImportBatch.objects.create(
                        created_by=request.user,
                        source_filename=getattr(form.cleaned_data["file"], "name", ""),
                        mode=form.cleaned_data["mode"],
                        is_dry_run=form.cleaned_data["dry_run"],
                    )
                try:
                    result = import_products(
                        uploaded_file=form.cleaned_data["file"],
                        mode=form.cleaned_data["mode"],
                        default_category=form.cleaned_data["default_category"],
                        default_currency=form.cleaned_data["default_currency"],
                        update_existing=form.cleaned_data["update_existing"],
                        create_missing_categories=form.cleaned_data["create_missing_categories"],
                        dry_run=form.cleaned_data["dry_run"],
                        import_batch=import_batch,
                    )
                except ValueError as exc:
                    if import_batch:
                        import_batch.delete()
                    messages.error(request, str(exc))
                else:
                    if import_batch:
                        import_batch.created_products = result.created_products
                        import_batch.updated_products = result.updated_products
                        import_batch.skipped_products = result.skipped_products
                        import_batch.created_options = result.created_options
                        import_batch.updated_options = result.updated_options
                        import_batch.skipped_options = result.skipped_options
                        import_batch.created_categories = result.created_categories
                        import_batch.error_count = len(result.errors)
                        import_batch.save(
                            update_fields=[
                                "created_products",
                                "updated_products",
                                "skipped_products",
                                "created_options",
                                "updated_options",
                                "skipped_options",
                                "created_categories",
                                "error_count",
                            ]
                        )
                    summary = (
                        f"Products: {result.created_products} created, "
                        f"{result.updated_products} updated, "
                        f"{result.skipped_products} skipped. "
                        f"Options: {result.created_options} created, "
                        f"{result.updated_options} updated, "
                        f"{result.skipped_options} skipped. "
                        f"Categories: {result.created_categories} created."
                    )
                    level = messages.SUCCESS if not result.errors else messages.WARNING
                    messages.add_message(request, level, summary)
                    if result.errors:
                        errors = result.errors[:10]
                        if len(result.errors) > 10:
                            errors.append(f"...and {len(result.errors) - 10} more.")
                        messages.warning(request, "Errors: " + " | ".join(errors))
                    if not form.cleaned_data["dry_run"]:
                        opts = self.model._meta
                        return redirect(
                            reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")
                        )
        else:
            form = ProductImportForm(
                initial={
                    "default_currency": getattr(settings, "DEFAULT_CURRENCY_CODE", "CAD"),
                }
            )

        context = {
            **self.admin_site.each_context(request),
            "title": "Import products",
            "form": form,
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
            "has_view_permission": self.has_view_permission(request),
            "product_changelist_url": reverse(
                f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist"
            ),
        }
        return TemplateResponse(request, "admin/store/product/import.html", context)

    @admin.display(description="Category", ordering="category__name")
    def category_short(self, obj):
        if not getattr(obj, "category", None):
            return "—"
        name = obj.category.name or ""
        if ">" in name:
            short = name.split(">")[-1].strip()
            return format_html('<span title="{}">{}</span>', name, short)
        return name

    def _junk_queryset(self):
        return Product.objects.filter(
            sku__startswith="product-",
            name__startswith="product-",
            price=0,
            inventory=0,
            category__name__iexact="Uncategorized",
            is_active=True,
            cleanup_batch__isnull=True,
        )

    def _missing_image_queryset(self, *, include_inactive: bool):
        qs = Product.objects.filter(Q(main_image__isnull=True) | Q(main_image=""))
        if not include_inactive:
            qs = qs.filter(is_active=True)
        return qs

    def _autofill_source_template(self) -> str:
        return getattr(
            settings,
            "PRODUCT_AUTOFILL_IMAGE_URL",
            "https://picsum.photos/seed/{seed}/1200/1200",
        )

    def _placeholder_images_setting(self):
        raw = getattr(settings, "PRODUCT_PLACEHOLDER_IMAGES", None)
        if not raw:
            return []
        if isinstance(raw, (list, tuple)):
            values = list(raw)
        elif isinstance(raw, str):
            values = [item.strip() for item in raw.replace("\n", ",").split(",")]
        else:
            try:
                values = list(raw)
            except TypeError:
                return []
        cleaned = []
        for value in values:
            if not value:
                continue
            item = str(value).strip()
            if not item:
                continue
            if item.startswith(("http://", "https://")):
                cleaned.append(item)
            else:
                cleaned.append(item.lstrip("/"))
        return cleaned

    def _placeholder_images_from_storage(self, directory: str):
        if not directory:
            return []
        directory = directory.strip().strip("/")
        if not directory:
            return []
        try:
            _, files = default_storage.listdir(directory)
        except Exception:
            return []
        allowed_ext = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
        images = []
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext in allowed_ext:
                images.append(name)
        images.sort()
        return [f"{directory}/{name}" for name in images]

    def _pick_placeholder_image(self, images, product: Product) -> str:
        if not images:
            return ""
        idx = int(product.pk) % len(images)
        return images[idx]

    def _format_autofill_url(self, template: str, product: Product) -> str:
        seed = f"product-{product.pk}"
        return template.replace("{seed}", seed)

    def _matches_autofill_url(self, url: str, template: str) -> bool:
        if not url:
            return False
        if "{seed}" not in template:
            return url == template
        parts = template.split("{seed}")
        if not url.startswith(parts[0]) or not url.endswith(parts[-1]):
            return False
        pos = len(parts[0])
        for mid in parts[1:-1]:
            idx = url.find(mid, pos)
            if idx == -1:
                return False
            pos = idx + len(mid)
        return True

    def _autofill_candidate_queryset(self, template: str):
        qs = Product.objects.exclude(main_image__isnull=True).exclude(main_image="")
        if "{seed}" not in template:
            return qs.filter(main_image=template)
        parts = template.split("{seed}")
        prefix = parts[0]
        suffix = parts[-1]
        if prefix:
            qs = qs.filter(main_image__startswith=prefix)
        if suffix:
            qs = qs.filter(main_image__endswith=suffix)
        return qs

    def _main_image_name(self, product: Product) -> str:
        image = getattr(product, "main_image", None)
        if not image:
            return ""
        return getattr(image, "name", "") or str(image)

    def autofill_missing_photos_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied

        missing_active = self._missing_image_queryset(include_inactive=False).count()
        missing_inactive = (
            self._missing_image_queryset(include_inactive=True)
            .filter(is_active=False)
            .count()
        )
        include_inactive = bool(request.POST.get("include_inactive"))

        if request.method == "POST":
            missing_qs = self._missing_image_queryset(include_inactive=include_inactive)
            missing_count = missing_qs.count()
            if missing_count == 0:
                messages.info(request, "No products are missing a main image.")
                return redirect(
                    reverse(f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist")
                )

            source_template = self._autofill_source_template()
            updated = 0
            skipped = 0
            errors = []

            for product in missing_qs.iterator():
                if product.main_image:
                    skipped += 1
                    continue
                url = self._format_autofill_url(source_template, product)
                try:
                    Product.objects.filter(pk=product.pk).update(
                        main_image=url,
                        updated_at=timezone.now(),
                    )
                except Exception as exc:
                    errors.append(f"{product.pk}: {exc}")
                    continue
                updated += 1

            if updated:
                messages.success(request, f"Added photo URLs to {updated} products.")
            else:
                messages.warning(request, "No photo URLs were added.")
            if skipped:
                messages.info(request, f"Skipped {skipped} products already updated.")
            if errors:
                sample = "; ".join(errors[:5])
                if len(errors) > 5:
                    sample += f"; and {len(errors) - 5} more."
                messages.warning(request, f"Errors: {sample}")
            return redirect(
                reverse(f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist")
            )

        context = {
            **self.admin_site.each_context(request),
            "title": "Autofill missing photos",
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
            "has_view_permission": self.has_view_permission(request),
            "product_changelist_url": reverse(
                f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist"
            ),
            "missing_active": missing_active,
            "missing_inactive": missing_inactive,
            "include_inactive": include_inactive,
        }
        return TemplateResponse(
            request,
            "admin/store/product/autofill_missing_photos.html",
            context,
        )

    def autofill_placeholder_photos_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied

        missing_active = self._missing_image_queryset(include_inactive=False).count()
        missing_inactive = (
            self._missing_image_queryset(include_inactive=True)
            .filter(is_active=False)
            .count()
        )
        include_inactive = bool(request.POST.get("include_inactive"))

        settings_images = self._placeholder_images_setting()
        placeholder_dir = str(getattr(settings, "PRODUCT_PLACEHOLDER_IMAGE_DIR", "store/placeholders"))
        images = settings_images or self._placeholder_images_from_storage(placeholder_dir)
        source_label = "settings.PRODUCT_PLACEHOLDER_IMAGES" if settings_images else f"media:{placeholder_dir.strip().strip('/')}"
        usable_images = images[:4] if len(images) >= 4 else []
        can_run = len(usable_images) == 4

        if request.method == "POST":
            if not can_run:
                messages.error(
                    request,
                    f"Need 4 placeholder images. Found {len(images)}.",
                )
                return redirect(
                    reverse(f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_autofill_placeholder_photos")
                )

            missing_qs = self._missing_image_queryset(include_inactive=include_inactive)
            missing_count = missing_qs.count()
            if missing_count == 0:
                messages.info(request, "No products are missing a main image.")
                return redirect(
                    reverse(f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist")
                )

            updated = 0
            skipped = 0
            errors = []

            for product in missing_qs.iterator():
                if product.main_image:
                    skipped += 1
                    continue
                image_value = self._pick_placeholder_image(usable_images, product)
                if not image_value:
                    errors.append(f"{product.pk}: no placeholder image resolved")
                    continue
                try:
                    Product.objects.filter(pk=product.pk).update(
                        main_image=image_value,
                        updated_at=timezone.now(),
                    )
                except Exception as exc:
                    errors.append(f"{product.pk}: {exc}")
                    continue
                updated += 1

            if updated:
                messages.success(request, f"Added placeholder photos to {updated} products.")
            else:
                messages.warning(request, "No placeholder photos were added.")
            if skipped:
                messages.info(request, f"Skipped {skipped} products already updated.")
            if errors:
                sample = "; ".join(errors[:5])
                if len(errors) > 5:
                    sample += f"; and {len(errors) - 5} more."
                messages.warning(request, f"Errors: {sample}")
            return redirect(
                reverse(f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist")
            )

        context = {
            **self.admin_site.each_context(request),
            "title": "Autofill placeholder photos",
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
            "has_view_permission": self.has_view_permission(request),
            "product_changelist_url": reverse(
                f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist"
            ),
            "missing_active": missing_active,
            "missing_inactive": missing_inactive,
            "include_inactive": include_inactive,
            "placeholder_images": usable_images,
            "placeholder_total": len(images),
            "placeholder_source": source_label,
            "placeholder_dir": placeholder_dir,
            "can_run": can_run,
        }
        return TemplateResponse(
            request,
            "admin/store/product/autofill_placeholder_photos.html",
            context,
        )

    def rollback_autofill_photos_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied

        source_template = self._autofill_source_template()
        candidate_qs = self._autofill_candidate_queryset(source_template)
        candidate_count = candidate_qs.count()

        if request.method == "POST":
            if candidate_count == 0:
                messages.info(request, "No autofilled photos found.")
                return redirect(
                    reverse(f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist")
                )

            cleared = 0
            skipped = 0
            for product in candidate_qs.iterator():
                image_name = self._main_image_name(product)
                if not self._matches_autofill_url(image_name, source_template):
                    skipped += 1
                    continue
                Product.objects.filter(pk=product.pk).update(
                    main_image=None,
                    updated_at=timezone.now(),
                )
                cleared += 1

            if cleared:
                messages.success(request, f"Cleared autofilled photos for {cleared} products.")
            else:
                messages.warning(request, "No autofilled photos were cleared.")
            if skipped:
                messages.info(request, f"Skipped {skipped} products that did not match the autofill pattern.")
            return redirect(
                reverse(f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist")
            )

        context = {
            **self.admin_site.each_context(request),
            "title": "Rollback autofill photos",
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
            "has_view_permission": self.has_view_permission(request),
            "product_changelist_url": reverse(
                f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist"
            ),
            "autofill_count": candidate_count,
        }
        return TemplateResponse(
            request,
            "admin/store/product/rollback_autofill_photos.html",
            context,
        )

    def cleanup_junk_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied

        criteria = "sku/name start with 'product-', price=0, inventory=0, category=Uncategorized"
        junk_qs = self._junk_queryset()
        junk_count = junk_qs.count()

        if request.method == "POST":
            if junk_count == 0:
                messages.info(request, "No junk products found.")
                return redirect(
                    reverse(f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist")
                )

            with transaction.atomic():
                batch = CleanupBatch.objects.create(
                    created_by=request.user,
                    criteria=criteria,
                    matched_products=junk_count,
                )
                deactivated = junk_qs.update(is_active=False, cleanup_batch=batch)
                batch.deactivated_products = deactivated
                batch.save(update_fields=["deactivated_products"])

            messages.success(request, f"Deactivated {deactivated} junk products.")
            return redirect(
                reverse(f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist")
            )

        context = {
            **self.admin_site.each_context(request),
            "title": "Cleanup junk products",
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
            "has_view_permission": self.has_view_permission(request),
            "product_changelist_url": reverse(
                f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist"
            ),
            "criteria": criteria,
            "junk_count": junk_count,
        }
        return TemplateResponse(request, "admin/store/product/cleanup_junk.html", context)

    def rollback_last_cleanup_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied

        batch = CleanupBatch.objects.filter(
            rolled_back_at__isnull=True,
        ).order_by("-created_at").first()
        if not batch:
            messages.warning(request, "No cleanup batches available to rollback.")
            return redirect(
                reverse(f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist")
            )

        if request.method == "POST":
            with transaction.atomic():
                products_qs = Product.objects.filter(cleanup_batch=batch)
                products_count = products_qs.count()
                products_qs.update(is_active=True, cleanup_batch=None)
                batch.rolled_back_at = timezone.now()
                batch.save(update_fields=["rolled_back_at"])

            messages.success(request, f"Rolled back cleanup #{batch.pk}: reactivated {products_count} products.")
            return redirect(
                reverse(f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist")
            )

        context = {
            **self.admin_site.each_context(request),
            "title": "Rollback last cleanup",
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
            "has_view_permission": self.has_view_permission(request),
            "product_changelist_url": reverse(
                f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist"
            ),
            "batch": batch,
        }
        return TemplateResponse(
            request,
            "admin/store/product/rollback_last_cleanup.html",
            context,
        )

    def rollback_last_import_view(self, request):
        if not self.has_delete_permission(request):
            raise PermissionDenied

        batch = ImportBatch.objects.filter(
            is_dry_run=False,
            rolled_back_at__isnull=True,
        ).order_by("-created_at").first()
        if not batch:
            messages.warning(request, "No import batches available to rollback.")
            return redirect(
                reverse(f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist")
            )

        if request.method == "POST":
            with transaction.atomic():
                options_qs = ProductOption.objects.filter(import_batch=batch)
                products_qs = Product.objects.filter(import_batch=batch)
                options_count = options_qs.count()
                products_count = products_qs.count()
                options_qs.delete()
                products_qs.delete()
                batch.rolled_back_at = timezone.now()
                batch.save(update_fields=["rolled_back_at"])

            messages.success(
                request,
                f"Rolled back import #{batch.pk}: deleted {products_count} products and {options_count} options.",
            )
            return redirect(
                reverse(f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist")
            )

        context = {
            **self.admin_site.each_context(request),
            "title": "Rollback last import",
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
            "has_view_permission": self.has_view_permission(request),
            "product_changelist_url": reverse(
                f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist"
            ),
            "batch": batch,
        }
        return TemplateResponse(
            request,
            "admin/store/product/rollback_last_import.html",
            context,
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
    list_display = ("name", "sku", "product", "price", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name", "sku", "product__name", "product__sku")
    autocomplete_fields = ("product",)
    ordering = ("product__name", "sort_order", "id")


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "created_by",
        "source_filename",
        "mode",
        "created_products",
        "created_options",
        "error_count",
        "rolled_back_at",
    )
    list_filter = ("mode", "is_dry_run", "rolled_back_at")
    search_fields = ("source_filename", "created_by__username")
    readonly_fields = (
        "created_at",
        "created_by",
        "source_filename",
        "mode",
        "is_dry_run",
        "created_products",
        "updated_products",
        "skipped_products",
        "created_options",
        "updated_options",
        "skipped_options",
        "created_categories",
        "error_count",
        "rolled_back_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(CleanupBatch)
class CleanupBatchAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "created_by",
        "criteria",
        "matched_products",
        "deactivated_products",
        "rolled_back_at",
    )
    list_filter = ("rolled_back_at",)
    search_fields = ("criteria", "created_by__username")
    readonly_fields = (
        "created_at",
        "created_by",
        "criteria",
        "matched_products",
        "deactivated_products",
        "rolled_back_at",
    )

    def has_add_permission(self, request):
        return False


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
    list_display = ("id", "created_display", "customer_name", "status_badge", "status", "has_reference_image", "total")
    list_display_links = ("id", "customer_name")
    list_editable = ("status",)  # редактирование статуса прямо в списке

    # убрали created_at из фильтров/иерархии, т.к. поле не гарантировано
    list_filter = ("status",)
    search_fields = ("customer_name", "email", "phone", "id")
    ordering = ("-id",)  # вместо date_hierarchy
    inlines = [OrderItemInline]
    readonly_fields = ("shipped_at", "completed_at", "cancelled_at", "reference_image_preview")
    fieldsets = (
        ("Status & ownership", {"fields": ("status", "user", "created_by")}),
        ("Contact", {"fields": ("customer_name", "email", "phone")}),
        ("Vehicle", {"fields": ("vehicle_make", "vehicle_model", "vehicle_year")}),
        ("Notes", {"fields": ("notes",)}),
        ("Client photo reference", {"fields": ("reference_image", "reference_image_preview")}),
        ("Timeline", {"fields": ("shipped_at", "completed_at", "cancelled_at")}),
    )

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

    @admin.display(description="Photo", boolean=True)
    def has_reference_image(self, obj):
        return bool(getattr(obj, "reference_image", None))

    @admin.display(description="Reference preview")
    def reference_image_preview(self, obj):
        if obj.reference_image:
            return format_html(
                '<a href="{0}" target="_blank" rel="noopener">'
                '<img src="{0}" style="max-height:160px;border-radius:10px;border:1px solid rgba(255,255,255,.2)"/>'
                "</a>",
                obj.reference_image.url,
            )
        return "—"


@admin.register(CustomFitmentRequest)
class CustomFitmentRequestAdmin(admin.ModelAdmin):
    list_display = ("created_at", "customer_name", "product_name", "status", "email", "phone")
    list_filter = ("status",)
    search_fields = (
        "customer_name",
        "email",
        "phone",
        "product_name",
        "vehicle",
        "submodel",
        "performance_goals",
        "budget",
    )
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("product",)
    fieldsets = (
        ("Request", {"fields": ("status", "product", "product_name", "source_url")}),
        ("Customer", {"fields": ("customer_name", "email", "phone")}),
        ("Build details", {"fields": ("vehicle", "submodel", "performance_goals", "budget", "timeline", "message")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
