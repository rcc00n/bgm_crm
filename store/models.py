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
    name = models.CharField("Название", max_length=120, unique=True)
    slug = models.SlugField("Слаг", unique=True)
    description = models.TextField("Описание", blank=True)
    image = models.ImageField(
        "Картинка",
        upload_to="store/categories/",
        blank=True, null=True,
        help_text="Загрузите обложку категории (соотношение ~16:9)"
    )

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def image_tag(self):
        if self.image:
            return format_html('<img src="{}" style="height:60px;border-radius:8px">', self.image.url)
        return "—"
    image_tag.short_description = "Превью"


class Product(models.Model):
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    sku = models.CharField(max_length=64, unique=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, default="USD")
    inventory = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    # media
    main_image = models.ImageField(upload_to="store/products/", blank=True, null=True)

    # attributes
    specs = models.JSONField(default=dict, blank=True)
    tags = ArrayField(models.CharField(max_length=32), blank=True, default=list)

    # compatibility
    compatible_models = models.ManyToManyField(CarModel, blank=True, related_name="compatible_products")

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


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="store/products/gallery/")
    alt = models.CharField(max_length=140, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]


# ─────────────────────────── Store: orders ───────────────────────────

class Order(models.Model):
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
    qty     = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])

    # ключевой момент: допускаем NULL и автоснапшотим при сохранении
    price_at_moment = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
    )

    def __str__(self):
        return f"{self.product} × {self.qty}"

    def save(self, *args, **kwargs):
        """
        Снимаем «снэпшот» цены, если поле пустое, чтобы сумма не зависела от
        будущих изменений цены продукта.
        """
        if self.price_at_moment is None and self.product_id:
            self.price_at_moment = self.product.price
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
            elif self.product_id and self.product.price is not None:
                price = Decimal(self.product.price)
            else:
                price = Decimal("0.00")
            return (qty * price).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError):
            return Decimal("0.00")
