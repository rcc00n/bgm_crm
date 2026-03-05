from decimal import Decimal, InvalidOperation
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.text import slugify

User = get_user_model()
logger = logging.getLogger(__name__)

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


# ─────────────────────────── Store: pricing settings ───────────────────────────

class StorePricingSettings(models.Model):
    price_multiplier_percent = models.PositiveSmallIntegerField(
        "Price multiplier (%)",
        default=100,
        help_text=(
            "Applies to all store product and option prices except in-house products. "
            "100 = no change, 110 = +10%. Use whole percents."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Store pricing settings"
        verbose_name_plural = "Store pricing settings"

    def __str__(self) -> str:
        return f"Store pricing ({self.price_multiplier_percent}%)"

    def clean(self):
        if StorePricingSettings.objects.exclude(pk=self.pk).exists():
            raise ValidationError("Only one store pricing settings record is allowed.")

    @classmethod
    def load(cls) -> "StorePricingSettings | None":
        return cls.objects.first()

    @classmethod
    def get_multiplier_percent(cls) -> int:
        obj = cls.load()
        if obj and obj.price_multiplier_percent is not None:
            return int(obj.price_multiplier_percent)
        return 100

    @classmethod
    def get_multiplier(cls) -> Decimal:
        percent = cls.get_multiplier_percent()
        try:
            return Decimal(str(percent)) / Decimal("100")
        except (InvalidOperation, TypeError):
            return Decimal("1.00")


def apply_store_price_multiplier(amount: Decimal, *, apply_multiplier: bool = True) -> Decimal:
    try:
        amount_value = Decimal(amount)
    except (InvalidOperation, TypeError):
        return Decimal("0.00")
    if not apply_multiplier:
        try:
            return amount_value.quantize(PRICE_QUANT)
        except (InvalidOperation, TypeError):
            return Decimal("0.00")
    multiplier = StorePricingSettings.get_multiplier()
    try:
        return (amount_value * multiplier).quantize(PRICE_QUANT)
    except (InvalidOperation, TypeError):
        return Decimal("0.00")


class StoreShippingSettings(models.Model):
    free_shipping_threshold_cad = models.DecimalField(
        "Free shipping threshold (Canada, CAD)",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text=(
            "Orders shipping to Canada at or above this subtotal are eligible for free shipping. "
            "Leave blank (or set to 0) to disable."
        ),
    )
    delivery_cost_under_threshold_cad = models.DecimalField(
        "Delivery cost under free-shipping threshold (Canada, CAD)",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text=(
            "Charged at checkout when shipping merch to Canada and the cart subtotal is below the free shipping threshold. "
            "Leave blank (or set to 0) to disable."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Store shipping settings"
        verbose_name_plural = "Store shipping settings"

    def __str__(self) -> str:
        threshold = self.free_shipping_threshold_cad
        if threshold:
            return f"Store shipping (free over CAD {threshold})"
        return "Store shipping"

    def clean(self):
        if StoreShippingSettings.objects.exclude(pk=self.pk).exists():
            raise ValidationError("Only one store shipping settings record is allowed.")

    @classmethod
    def load(cls) -> "StoreShippingSettings | None":
        return cls.objects.first()

    @classmethod
    def get_free_shipping_threshold_cad(cls) -> Decimal | None:
        obj = cls.load()
        if not obj:
            return None
        value = obj.free_shipping_threshold_cad
        if value is None:
            return None
        try:
            parsed = Decimal(value)
        except (InvalidOperation, TypeError):
            return None
        if parsed <= 0:
            return None
        return parsed.quantize(PRICE_QUANT)

    @classmethod
    def get_delivery_cost_under_threshold_cad(cls) -> Decimal | None:
        obj = cls.load()
        if not obj:
            return None
        value = obj.delivery_cost_under_threshold_cad
        if value is None:
            return None
        try:
            parsed = Decimal(value)
        except (InvalidOperation, TypeError):
            return None
        if parsed <= 0:
            return None
        return parsed.quantize(PRICE_QUANT)


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

    @property
    def display_name(self) -> str:
        name = self.name or ""
        if ">" in name:
            short = name.split(">")[-1].strip()
            return short or name
        return name

    def image_tag(self):
        if self.image:
            return format_html('<img src="{}" style="height:60px;border-radius:8px">', self.image.url)
        return "—"
    image_tag.short_description = "Preview"


class MerchCategory(models.Model):
    """
    Merch-only categories used on the /merch landing page.
    """
    name = models.CharField("Name", max_length=120, unique=True)
    slug = models.SlugField("Slug", max_length=140, unique=True, blank=True)
    description = models.TextField("Description", blank=True)
    cover_image = models.ImageField(
        "Cover image",
        upload_to="merch/categories/",
        blank=True,
        null=True,
        max_length=2048,
        help_text="Optional override. When empty, the first product image is used.",
    )
    cover_image_alt = models.CharField("Cover alt text", max_length=140, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Merch category"
        verbose_name_plural = "Merch categories"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def cover_preview(self):
        if getattr(self, "cover_image", None):
            try:
                return format_html(
                    '<img src="{}" style="height:60px;border-radius:8px">', self.cover_image.url
                )
            except Exception:
                return "—"
        return "—"
    cover_preview.short_description = "Cover"


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
    merch_category = models.ForeignKey(
        MerchCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        help_text="Optional merch category for the /merch landing page.",
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Base price before the global multiplier.",
    )
    unit_cost = models.DecimalField(
        "Cost / value (per unit)",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Optional internal cost used for margin reporting (not shown to customers).",
    )
    is_in_house = models.BooleanField(
        "In-house product",
        default=False,
        help_text="Exclude this product from the global price multiplier.",
    )
    printful_product_id = models.PositiveIntegerField(
        "Printful product ID",
        null=True,
        blank=True,
        db_index=True,
        help_text="Connected Printful sync product ID for merch items.",
    )
    printful_external_id = models.CharField(
        "Printful external ID",
        max_length=140,
        blank=True,
        default="",
        help_text="Optional external identifier mirrored from Printful.",
    )
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
    # Stores either a local path or a remote http(s) URL (see main_image_url).
    main_image = models.ImageField(upload_to="store/products/", blank=True, null=True, max_length=2048)

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
    option_column_1_label = models.CharField(
        "Option column 1 label",
        max_length=60,
        blank=True,
        help_text="Heading shown above the first option column on the product page.",
    )
    option_column_2_label = models.CharField(
        "Option column 2 label",
        max_length=60,
        blank=True,
        help_text="Heading shown above the second option column on the product page.",
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

    @property
    def main_image_url(self) -> str:
        image = getattr(self, "main_image", None)
        if not image:
            return ""
        name = getattr(image, "name", "") or str(image)
        if name.startswith("http://") or name.startswith("https://"):
            return name
        try:
            return image.url
        except Exception:
            return ""

    @property
    def main_image_is_remote(self) -> bool:
        image = getattr(self, "main_image", None)
        if not image:
            return False
        name = getattr(image, "name", "") or str(image)
        return name.startswith(("http://", "https://"))

    @property
    def main_image_local(self):
        """
        Template-friendly handle for thumbnailing.
        Sorl/easy-thumbnail style libraries generally expect a real file object, not a remote URL.
        """
        image = getattr(self, "main_image", None)
        if not image or self.main_image_is_remote:
            return None
        return image

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

    def get_selectable_options(self):
        """
        Active options that are selectable (non-separator).
        """
        cache = getattr(self, "_prefetched_objects_cache", {})
        if cache and "options" in cache:
            return [
                opt for opt in cache["options"]
                if getattr(opt, "is_active", False) and not getattr(opt, "is_separator", False)
            ]
        return list(self.options.filter(is_active=True, is_separator=False).order_by("sort_order", "id"))

    @property
    def has_active_options(self) -> bool:
        cache = getattr(self, "_prefetched_objects_cache", {})
        if cache and "options" in cache:
            return any(opt.is_active and not getattr(opt, "is_separator", False) for opt in cache["options"])
        return self.options.filter(is_active=True, is_separator=False).exists()

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

    def get_active_discount(self, today=None):
        today = today or timezone.now().date()
        cache = getattr(self, "_prefetched_objects_cache", {})
        if cache and "discounts" in cache:
            for disc in cache["discounts"]:
                if disc.start_date <= today <= disc.end_date:
                    return disc
            return None
        return self.discounts.filter(start_date__lte=today, end_date__gte=today).first()

    def get_discounted_unit_price(self, option=None) -> Decimal:
        """
        Returns the unit price after any active product discount.
        """
        base = self.get_unit_price(option)
        discount = self.get_active_discount()
        if discount and not self.contact_for_estimate:
            multiplier = Decimal("1") - (Decimal(discount.discount_percent) / Decimal("100"))
            return (base * multiplier).quantize(PRICE_QUANT)
        return base

    def get_discounted_display_price(self) -> Decimal:
        """
        Returns the public-facing (discounted) display price.
        """
        base = self.display_price
        discount = self.get_active_discount()
        if discount and not self.contact_for_estimate:
            multiplier = Decimal("1") - (Decimal(discount.discount_percent) / Decimal("100"))
            return (base * multiplier).quantize(PRICE_QUANT)
        return base

    @property
    def public_price(self) -> Decimal:
        return self.get_discounted_display_price()

    @property
    def old_price(self) -> Decimal | None:
        discount = self.get_active_discount()
        if discount and not self.contact_for_estimate:
            return self.display_price
        return None

    @property
    def active_discount_percent(self) -> int:
        discount = self.get_active_discount()
        return int(getattr(discount, "discount_percent", 0) or 0)

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
            amount = Decimal(raw_value)
        except (InvalidOperation, TypeError):
            return Decimal("0.00")
        return apply_store_price_multiplier(amount, apply_multiplier=not self.is_in_house)

    def _option_price_values(self):
        apply_multiplier = not self.is_in_house
        for opt in self.get_selectable_options():
            value = getattr(opt, "price", None)
            if value is not None:
                try:
                    amount = Decimal(value)
                except (InvalidOperation, TypeError):
                    continue
                yield apply_store_price_multiplier(amount, apply_multiplier=apply_multiplier)

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


class ProductDiscount(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="discounts")
    discount_percent = models.PositiveIntegerField(help_text="Percent of discount")
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        verbose_name = "Product Discount"
        verbose_name_plural = "Product Discounts"
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.discount_percent}% off on {self.product.name} ({self.start_date} – {self.end_date})"

    def is_active(self):
        today = timezone.now().date()
        return self.start_date <= today <= self.end_date


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
    is_separator = models.BooleanField(
        "Separator",
        default=False,
        help_text="Show this option as a non-selectable separator in the option list.",
    )
    option_column = models.PositiveSmallIntegerField(
        "Display column",
        default=1,
        choices=((1, "Column 1"), (2, "Column 2")),
        help_text="Which option column to show this option under on the product page.",
    )
    price = models.DecimalField(
        "Price override",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        null=True,
        blank=True,
        help_text=(
            "Leave empty to inherit the product price. "
            "Global multiplier still applies unless the product is in-house."
        ),
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
    printful_sync_variant_id = models.PositiveIntegerField(
        "Printful sync variant ID",
        null=True,
        blank=True,
        db_index=True,
        help_text="Connected Printful sync variant ID for merch fulfillment.",
    )
    printful_variant_id = models.PositiveIntegerField(
        "Printful catalog variant ID",
        null=True,
        blank=True,
        db_index=True,
        help_text="Underlying Printful catalog variant ID when available.",
    )
    printful_external_id = models.CharField(
        "Printful external ID",
        max_length=140,
        blank=True,
        default="",
        help_text="Optional external variant identifier mirrored from Printful.",
    )

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

    @property
    def discounted_price(self) -> Decimal:
        return self.product.get_discounted_unit_price(self)


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
    review_request_sent_at = models.DateTimeField(null=True, blank=True)

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
        help_text="Optional reference image for logos, artwork, inspiration, or fitment examples uploaded at checkout.",
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

    # totals
    shipping_cost = models.DecimalField(
        "Shipping / delivery cost",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
        help_text="Delivery cost applied at checkout (before GST/fees).",
    )
    tracking_numbers = models.TextField(
        "Tracking numbers",
        blank=True,
        default="",
        help_text="One per line. Shown in the client portal after shipping.",
    )
    tracking_url = models.URLField(
        "Tracking link",
        blank=True,
        default="",
        help_text="Optional carrier tracking URL shown in the client portal.",
    )
    printful_order_id = models.PositiveIntegerField(
        "Printful order ID",
        null=True,
        blank=True,
        db_index=True,
        help_text="Connected Printful order ID after merch fulfillment submission.",
    )
    printful_external_id = models.CharField(
        "Printful external ID",
        max_length=140,
        blank=True,
        default="",
        db_index=True,
        help_text="Idempotent external order ID used when creating Printful orders.",
    )
    printful_status = models.CharField(
        "Printful status",
        max_length=40,
        blank=True,
        default="",
        db_index=True,
        help_text="Last known Printful order status from API/webhooks.",
    )
    printful_shipping_rate_id = models.CharField(
        "Printful shipping rate ID",
        max_length=80,
        blank=True,
        default="",
        help_text="Chosen Printful shipping rate identifier from checkout.",
    )
    printful_shipping_name = models.CharField(
        "Printful shipping method",
        max_length=140,
        blank=True,
        default="",
        help_text="Customer-facing Printful shipping method label used at checkout.",
    )
    printful_shipping_cost = models.DecimalField(
        "Printful shipping cost",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
        help_text="Shipping amount returned by Printful for the selected rate.",
    )
    printful_shipping_currency = models.CharField(
        "Printful shipping currency",
        max_length=8,
        blank=True,
        default="",
        help_text="Currency code returned by Printful shipping/order APIs.",
    )
    printful_tracking_data = models.JSONField(
        "Printful tracking payload",
        default=list,
        blank=True,
        help_text="Normalized tracking entries received from Printful webhooks.",
    )
    printful_last_synced_at = models.DateTimeField(
        "Printful last synced at",
        null=True,
        blank=True,
        help_text="When this order was last updated from Printful.",
    )
    printful_submitted_at = models.DateTimeField(
        "Printful submitted at",
        null=True,
        blank=True,
        help_text="When this order was first submitted to Printful.",
    )
    printful_error = models.TextField(
        "Printful error",
        blank=True,
        default="",
        help_text="Last fulfillment error returned by Printful, if any.",
    )

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
        try:
            total += Decimal(str(getattr(self, "shipping_cost", None) or "0"))
        except Exception:
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

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        old_status = None
        if not is_new and self.pk:
            try:
                old_status = (
                    Order.objects.filter(pk=self.pk)
                    .values_list("status", flat=True)
                    .first()
                )
            except Exception:
                old_status = None

        status_changed = old_status is not None and self.status != old_status
        if status_changed:
            now = timezone.now()
            if self.status == self.STATUS_SHIPPED and not self.shipped_at:
                self.shipped_at = now
            elif self.status == self.STATUS_COMPLETED and not self.completed_at:
                self.completed_at = now
            elif self.status == self.STATUS_CANCELLED and not self.cancelled_at:
                self.cancelled_at = now

            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                update_fields = set(update_fields)
                update_fields.update({"status"})
                if self.shipped_at:
                    update_fields.add("shipped_at")
                if self.completed_at:
                    update_fields.add("completed_at")
                if self.cancelled_at:
                    update_fields.add("cancelled_at")
                kwargs["update_fields"] = list(update_fields)

        super().save(*args, **kwargs)

        if status_changed:
            transaction.on_commit(lambda: self._send_status_update(old_status))

    def _send_status_update(self, old_status: str | None):
        recipient = (self.email or "").strip()
        if not recipient:
            return

        status_templates = {
            self.STATUS_PROCESSING: "order_status_processing",
            self.STATUS_SHIPPED: "order_status_shipped",
            self.STATUS_COMPLETED: "order_status_completed",
            self.STATUS_CANCELLED: "order_status_cancelled",
        }
        template_slug = status_templates.get(self.status)
        if not template_slug:
            return

        from core.email_templates import email_brand_name
        brand = email_brand_name()
        currency_symbol = getattr(settings, "DEFAULT_CURRENCY_SYMBOL", "$") or "$"
        currency_code = getattr(settings, "DEFAULT_CURRENCY_CODE", "").upper()
        order_total = self.total
        total_text = f"{currency_symbol}{order_total} {currency_code}".strip()
        from core.email_templates import base_email_context, join_text_sections, render_email_template
        context = base_email_context(
            {
                "brand": brand,
                "customer_name": self.customer_name,
                "order_id": self.pk,
                "order_status": self.get_status_display(),
                "order_total": total_text,
            }
        )
        template = render_email_template(template_slug, context)
        detail_lines = [
            f"Order #: {self.pk}",
            f"Status: {self.get_status_display()}",
            f"Order total: {total_text}",
        ]

        link_lines: list[str] = []
        link_rows: list[tuple[str, str]] = []
        cta_label = template.cta_label
        cta_url = getattr(settings, "COMPANY_WEBSITE", "")
        if self.status == self.STATUS_COMPLETED:
            base = (getattr(settings, "COMPANY_WEBSITE", "") or "").strip()
            if base and not base.startswith(("http://", "https://")):
                base = f"https://{base}"
            base = base.rstrip("/")

            raw_review = (getattr(settings, "ORDER_REVIEW_URL", "") or "").strip() or "/review/"
            if raw_review.startswith(("http://", "https://")):
                review_url = raw_review
            elif base:
                review_url = f"{base}/{raw_review.lstrip('/')}"
            else:
                review_url = ""

            if review_url:
                link_lines = [f"Leave a review: {review_url}"]
                link_rows = [("Leave a review", review_url)]
                cta_label = "Leave a review"
                cta_url = review_url

        text_body = join_text_sections(
            [template.greeting],
            template.intro_lines,
            detail_lines,
            link_lines,
            template.footer_lines,
        )

        sender = (
            getattr(settings, "DEFAULT_FROM_EMAIL", None)
            or getattr(settings, "SUPPORT_EMAIL", None)
        )
        if not sender:
            return

        try:
            items = list(self.items.select_related("product", "option").all())
        except Exception:
            items = []

        item_rows = []
        for it in items:
            name = getattr(it.product, "name", "Item")
            if getattr(it, "option", None):
                name = f"{name} ({it.option.name})"
            item_rows.append((name, f"x {it.qty}"))

        try:
            from core.emails import build_email_html, send_html_email

            html_body = build_email_html(
                title=template.title,
                preheader=template.preheader,
                greeting=template.greeting,
                intro_lines=template.intro_lines,
                detail_rows=[
                    ("Order #", self.pk),
                    ("Status", self.get_status_display()),
                    ("Order total", total_text),
                ],
                item_rows=item_rows,
                notice_title=template.notice_title or None,
                notice_lines=template.notice_lines,
                footer_lines=template.footer_lines,
                cta_label=cta_label,
                cta_url=cta_url,
                link_rows=link_rows,
            )
            send_html_email(
                subject=template.subject,
                text_body=text_body,
                html_body=html_body,
                from_email=sender,
                recipient_list=[recipient],
                email_type=template_slug,
            )
        except Exception:
            logger.exception(
                "Failed to send order status update for order %s (from %s to %s)",
                self.pk,
                old_status,
                self.status,
            )

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


class OrderPromoCode(models.Model):
    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name="promo",
    )
    promocode = models.ForeignKey(
        "core.PromoCode",
        on_delete=models.PROTECT,
        related_name="order_promos",
    )
    discount_percent = models.PositiveIntegerField(default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Order Promo Code"
        verbose_name_plural = "Order Promo Codes"

    def __str__(self):
        code = getattr(self.promocode, "code", "") or "Promo"
        return f"{code} for Order #{self.order_id}"


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


class AbandonedCart(models.Model):
    """
    Stores abandoned cart snapshots for follow-up emails.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="abandoned_carts",
    )
    session_key = models.CharField(max_length=64, blank=True, db_index=True)
    email = models.EmailField(db_index=True)
    cart_items = models.JSONField(default=list)
    cart_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    currency_code = models.CharField(max_length=8, blank=True)
    currency_symbol = models.CharField(max_length=8, blank=True)
    last_activity_at = models.DateTimeField(default=timezone.now, db_index=True)
    recovered_at = models.DateTimeField(null=True, blank=True, db_index=True)
    email_1_sent_at = models.DateTimeField(null=True, blank=True)
    email_2_sent_at = models.DateTimeField(null=True, blank=True)
    email_3_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Abandoned cart"
        verbose_name_plural = "Abandoned carts"

    def __str__(self) -> str:
        return f"{self.email} — {self.cart_total}"


class PrintfulWebhookEvent(models.Model):
    event_type = models.CharField(max_length=80, db_index=True)
    event_hash = models.CharField(max_length=64, unique=True)
    order = models.ForeignKey(
        Order,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="printful_webhook_events",
    )
    payload = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at", "-id"]

    def __str__(self) -> str:
        return f"{self.event_type or 'printful'} @ {self.received_at:%Y-%m-%d %H:%M}"


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
    reference_image = models.ImageField(
        upload_to="store/fitment_attachments/",
        null=True,
        blank=True,
        help_text="Optional customer reference photo for fitment context.",
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


# ─────────────────────────── Store: reviews ───────────────────────────

class StoreReview(models.Model):
    """
    Customer-submitted reviews that require staff approval before being shown publicly.
    """

    class Status(models.TextChoices):
        PENDING = ("pending", "Pending")
        APPROVED = ("approved", "Approved")
        REJECTED = ("rejected", "Rejected")

    product = models.ForeignKey(
        Product,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviews",
        help_text="Optional. When set, this review will appear on the product page.",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="store_reviews",
        help_text="Optional link to the logged-in user who submitted the review.",
    )

    reviewer_name = models.CharField(max_length=160)
    reviewer_email = models.EmailField(blank=True)
    reviewer_title = models.CharField(
        max_length=160,
        blank=True,
        help_text="Optional context such as vehicle/platform, role, or short descriptor.",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Rating between 1 (worst) and 5 (best).",
    )
    title = models.CharField(max_length=160, blank=True)
    body = models.TextField(help_text="Review text that may be edited by staff before publishing.")
    source_url = models.URLField(blank=True, help_text="Page URL where the review was submitted from.")

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_store_reviews",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Store review"
        verbose_name_plural = "Store reviews"
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["product", "status", "created_at"]),
        ]

    def __str__(self) -> str:
        scope = f" for {self.product}" if self.product_id else ""
        return f"{self.rating}★ by {self.reviewer_name}{scope}"

    @property
    def star_range(self):
        return range(self.rating or 0)
