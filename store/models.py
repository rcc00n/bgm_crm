from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.text import slugify

User = get_user_model()

PRICE_QUANT = Decimal("0.01")


# ─────────────────────────── Catalog: car directories ───────────────────────────

class CarMake(models.Model):
    name = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CarModel(models.Model):
    make = models.ForeignKey(CarMake, on_delete=models.CASCADE, related_name="models")
    name = models.CharField(max_length=64)
    year_from = models.PositiveIntegerField(null=True, blank=True)
    year_to = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = ("make", "name", "year_from", "year_to")
        ordering = ["make__name", "name", "year_from"]

    def __str__(self):
        yr = f"{self.year_from or ''}-{self.year_to or ''}".strip("-")
        return f"{self.make} {self.name}{(' ' + yr) if yr else ''}"


# ─────────────────────────── Store: categories / products ───────────────────────────

class Category(models.Model):
    name = models.CharField("Name", max_length=120, unique=True)
    slug = models.SlugField("Slug", unique=True)
    description = models.TextField("Description", blank=True)
    image = models.ImageField(
        "Image",
        upload_to="store/categories/",
        blank=True, null=True,
        help_text="Upload a 16:9 category cover"
    )

    class Meta:
        verbose_name = "Category"
        verbose_name_plural = "Categories"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def image_tag(self):
        if self.image:
            return format_html('<img src="{}" style="height:60px;border-radius:8px">', self.image.url)
        return "—"
    image_tag.short_description = "Preview"


class ImportBatch(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="import_batches",
    )
    source_filename = models.CharField(max_length=255, blank=True)
    mode = models.CharField(max_length=32, blank=True)
    is_dry_run = models.BooleanField(default=False)
    created_products = models.PositiveIntegerField(default=0)
    updated_products = models.PositiveIntegerField(default=0)
    skipped_products = models.PositiveIntegerField(default=0)
    created_options = models.PositiveIntegerField(default=0)
    updated_options = models.PositiveIntegerField(default=0)
    skipped_options = models.PositiveIntegerField(default=0)
    created_categories = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    rolled_back_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        label = self.created_at.strftime("%Y-%m-%d %H:%M")
        return f"Import #{self.pk} — {label}"


class CleanupBatch(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cleanup_batches",
    )
    criteria = models.CharField(max_length=255, blank=True)
    matched_products = models.PositiveIntegerField(default=0)
    deactivated_products = models.PositiveIntegerField(default=0)
    rolled_back_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        label = self.created_at.strftime("%Y-%m-%d %H:%M")
        return f"Cleanup #{self.pk} — {label}"


class Product(models.Model):
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    sku = models.CharField(max_length=64, unique=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, default=settings.DEFAULT_CURRENCY_CODE)
    inventory = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    import_batch = models.ForeignKey(
        ImportBatch,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="products",
    )
    cleanup_batch = models.ForeignKey(
        CleanupBatch,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="products",
    )

    # media
    main_image = models.ImageField(upload_to="store/products/", blank=True, null=True)

    # attributes
    specs = models.JSONField(default=dict, blank=True)
    tags = ArrayField(models.CharField(max_length=32), blank=True, default=list)

    # compatibility
    compatible_models = models.ManyToManyField(CarModel, blank=True, related_name="compatible_products")
    compatibility = models.TextField(blank=True, help_text="Free-form compatibility notes shown on the product page.")

    contact_for_estimate = models.BooleanField(
        "Contact for estimate",
        default=False,
        help_text='Show “Contact for estimate” instead of the numeric price on the storefront.',
    )
    estimate_from_price = models.DecimalField(
        "Starting from",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Optional hint that displays as “From $X”.",
    )

    # SEO/meta
    short_description = models.CharField(max_length=240, blank=True)
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["category", "is_active"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        # под шаблоны, где используется {% url 'store-product' slug=p.slug %}
        return reverse("store-product", kwargs={"slug": self.slug})

    def get_active_options(self):
        """
        Ordered list of active options. Prefetch-aware to avoid extra queries.
        """
        cache = getattr(self, "_prefetched_objects_cache", {})
        if cache and "options" in cache:
            return [opt for opt in cache["options"] if getattr(opt, "is_active", False)]
        return list(self.options.filter(is_active=True).order_by("sort_order", "id"))

    @property
    def has_active_options(self) -> bool:
        cache = getattr(self, "_prefetched_objects_cache", {})
        if cache and "options" in cache:
            return any(opt.is_active for opt in cache["options"])
        return self.options.filter(is_active=True).exists()

    def get_companion_items(self, limit: int = 3):
        """
        Deterministically rotates the active catalog to get a varied (but stable) set of companions.
        """
        qs = Product.objects.filter(is_active=True).exclude(pk=self.pk).order_by("id")
        ids = list(qs.values_list("id", flat=True))
        if not ids:
            return []
        seed_source = self.slug or self.name or str(self.pk)
        seed = sum(ord(ch) for ch in seed_source)
        idx = seed % len(ids)
        ordered_ids = ids[idx:] + ids[:idx]
        pick_ids = ordered_ids[:limit]
        companions = list(Product.objects.filter(id__in=pick_ids).select_related("category"))
        companions.sort(key=lambda obj: pick_ids.index(obj.id))
        return companions

    def get_unit_price(self, option=None) -> Decimal:
        """
        Returns the effective unit price for the product, respecting option overrides.
        """
        raw_value = None
        if option and getattr(option, "price", None) is not None:
            raw_value = option.price
        else:
            raw_value = self.price
        try:
            return Decimal(raw_value).quantize(PRICE_QUANT)
        except (InvalidOperation, TypeError):
            return Decimal("0.00")

    def _option_price_values(self):
        for opt in self.get_active_options():
            value = getattr(opt, "price", None)
            if value is not None:
                yield value

    @property
    def display_price(self) -> Decimal:
        overrides = []
        for value in self._option_price_values():
            try:
                overrides.append(Decimal(value))
            except (InvalidOperation, TypeError):
                continue
        if overrides:
            return min(overrides).quantize(PRICE_QUANT)
        return self.get_unit_price()

    @property
    def has_option_price_overrides(self) -> bool:
        for _ in self._option_price_values():
            return True
        return False


class ProductOption(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="options",
        verbose_name="Product",
    )
    name = models.CharField("Name", max_length=120)
    sku = models.CharField("SKU", max_length=64, unique=True, null=True, blank=True)
    description = models.CharField("Description", max_length=240, blank=True)
    price = models.DecimalField(
        "Price override",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        null=True,
        blank=True,
        help_text="Leave empty to inherit the product price.",
    )
    is_active = models.BooleanField(
        "Active",
        default=False,
        help_text="Inactive options are hidden on the product page.",
    )
    import_batch = models.ForeignKey(
        ImportBatch,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="options",
    )
    sort_order = models.PositiveIntegerField("Sort order", default=0)

    class Meta:
        verbose_name = "Product option"
        verbose_name_plural = "Product options"
        ordering = ["sort_order", "id"]
        unique_together = ("product", "name")

    def __str__(self):
        label = f"{self.product}: {self.name}"
        return f"{label} ({self.sku})" if self.sku else label

    def get_effective_price(self) -> Decimal:
        return self.product.get_unit_price(self)

    @property
    def unit_price(self) -> Decimal:
        return self.get_effective_price()

    @property
    def has_custom_price(self) -> bool:
        return self.price is not None


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="store/products/gallery/")
    alt = models.CharField(max_length=140, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]


# ─────────────────────────── Store: orders ───────────────────────────

class Order(models.Model):
    class PaymentStatus(models.TextChoices):
        UNPAID = ("unpaid", "Unpaid")
        PAID = ("paid", "Paid")
        FAILED = ("failed", "Failed")

    class PaymentMode(models.TextChoices):
        FULL = ("full", "Pay in full")
        DEPOSIT = ("deposit_50", "50% deposit")

    STATUS_PROCESSING = "processing"   # В обработке
    STATUS_SHIPPED    = "shipped"      # Отправлен
    STATUS_COMPLETED  = "completed"    # Выполнен
    STATUS_CANCELLED  = "cancelled"    # Отменён

    STATUS_CHOICES = (
        (STATUS_PROCESSING, "processing"),
        (STATUS_SHIPPED,    "shipped"),
        (STATUS_COMPLETED,  "completed"),
        (STATUS_CANCELLED,  "cancelled"),
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PROCESSING,
        db_index=True,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="orders"
    )

    shipped_at   = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    # contact
    customer_name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True)

    # vehicle
    vehicle_make = models.CharField(max_length=64, blank=True)
    vehicle_model = models.CharField(max_length=64, blank=True)
    vehicle_year = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    reference_image = models.ImageField(
        upload_to="store/order_attachments/",
        null=True,
        blank=True,
        help_text="Optional photo reference uploaded at checkout.",
    )

    # payment
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
        db_index=True,
    )
    payment_mode = models.CharField(
        max_length=20,
        choices=PaymentMode.choices,
        default=PaymentMode.FULL,
    )
    payment_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    payment_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    payment_balance_due = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    payment_processor = models.CharField(max_length=32, blank=True, default="")
    payment_id = models.CharField(max_length=140, blank=True, default="")
    payment_receipt_url = models.URLField(blank=True, default="")
    payment_card_brand = models.CharField(max_length=40, blank=True, default="")
    payment_last4 = models.CharField(max_length=8, blank=True, default="")

    # who created
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"Order #{self.pk} — {self.customer_name} — {self.get_status_display()}"

    @property
    def total(self) -> Decimal:
        # безопасная сумма: всегда Decimal c точностью 0.01
        total = Decimal("0.00")
        for it in self.items.all():
            try:
                total += it.subtotal
            except Exception:
                # если вдруг какая-то позиция битая — не валим всё
                pass
        return total.quantize(Decimal("0.01"))

    def set_status(self, new_status: str, *, save=True):
        self.status = new_status
        now = timezone.now()
        if new_status == self.STATUS_SHIPPED:
            self.shipped_at = now
        elif new_status == self.STATUS_COMPLETED:
            self.completed_at = now
        elif new_status == self.STATUS_CANCELLED:
            self.cancelled_at = now
        if save:
            self.save(update_fields=["status", "shipped_at", "completed_at", "cancelled_at"])

    STATUS_UI = {
        STATUS_PROCESSING: ("processing", "#f5a623"),
        STATUS_SHIPPED:    ("shipped",    "#2d9cdb"),
        STATUS_COMPLETED:  ("completed",  "#17d45b"),
        STATUS_CANCELLED:  ("cancelled",  "#ff5c72"),
    }

    @property
    def status_label(self):
        return self.STATUS_UI.get(self.status, (self.status, "#bbb"))[0]

    @property
    def status_color(self):
        return self.STATUS_UI.get(self.status, (self.status, "#bbb"))[1]


class OrderItem(models.Model):
    order   = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    option  = models.ForeignKey(
        ProductOption,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="order_items",
        help_text="Option chosen by the customer.",
    )
    qty     = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])

    # ключевой момент: допускаем NULL и автоснапшотим при сохранении
    price_at_moment = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
    )

    def __str__(self):
        if self.option_id:
            return f"{self.product} [{self.option.name}] × {self.qty}"
        return f"{self.product} × {self.qty}"

    def save(self, *args, **kwargs):
        """
        Снимаем «снэпшот» цены, если поле пустое, чтобы сумма не зависела от
        будущих изменений цены продукта.
        """
        option_obj = None
        if self.option_id:
            option_obj = self.option
            if option_obj and self.product_id and option_obj.product_id != self.product_id:
                raise ValueError("Selected option does not belong to the product.")

        if self.price_at_moment is None and self.product_id:
            self.price_at_moment = self.product.get_unit_price(option_obj)
        super().save(*args, **kwargs)

    @property
    def subtotal(self) -> Decimal:
        """
        Null-safe подсчёт: если snapshot-цены нет — берём текущую цену продукта,
        если и её нет (теоретически) — возвращаем 0.00.
        """
        try:
            qty = Decimal(self.qty or 0)
            if self.price_at_moment is not None:
                price = Decimal(self.price_at_moment)
            elif self.product_id:
                option_obj = self.option if self.option_id else None
                price = self.product.get_unit_price(option_obj)
            else:
                price = Decimal("0.00")
            return (qty * price).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError):
            return Decimal("0.00")


# ─────────────────────────── Custom fitment / quote requests ───────────────────────────

class CustomFitmentRequest(models.Model):
    class Status(models.TextChoices):
        NEW = ("new", "New")
        IN_PROGRESS = ("in_progress", "In progress")
        RESPONDED = ("responded", "Responded")

    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fitment_requests",
        help_text="Product the request originated from (if it still exists).",
    )
    product_name = models.CharField(
        max_length=180,
        blank=True,
        help_text="Snapshot of the product name so context is not lost if the product is removed.",
    )

    customer_name = models.CharField("Customer name", max_length=140)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    vehicle = models.CharField(
        max_length=180,
        blank=True,
        help_text="Chassis, platform, or vehicle description shared by the customer.",
    )
    submodel = models.CharField(
        max_length=140,
        blank=True,
        help_text="Trim or submodel details provided by the customer.",
    )
    performance_goals = models.CharField(
        max_length=200,
        blank=True,
        help_text="Power goals or intended usage spelled out by the customer.",
    )
    budget = models.CharField(
        max_length=120,
        blank=True,
        help_text="Budget or target spend shared by the customer.",
    )
    timeline = models.CharField(
        max_length=140,
        blank=True,
        help_text="Requested timing or deadline for the build.",
    )
    message = models.TextField(
        blank=True,
        help_text="Free-form notes provided by the customer.",
    )
    source_url = models.URLField(
        blank=True,
        help_text="Where on the site the request originated.",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Custom fitment request"
        verbose_name_plural = "Custom fitment requests"

    def __str__(self):
        return f"{self.customer_name} — {self.product_name or 'Custom build'}"

    def save(self, *args, **kwargs):
        """
        Preserve product context even if the catalog entry disappears later.
        """
        if self.product and not self.product_name:
            self.product_name = self.product.name
        super().save(*args, **kwargs)
