from django.db import models
from django.utils.text import slugify
from django.urls import reverse
from django.core.validators import MinValueValidator
from django.contrib.postgres.fields import ArrayField
from django.contrib.auth import get_user_model

User = get_user_model()


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
        yr = f" {self.year_from or ''}-{self.year_to or ''}".strip()
        return f"{self.make} {self.name}{(' ' + yr) if yr else ''}"


# models_store.py (store_folder)
from django.db import models
from django.utils.html import format_html

class Category(models.Model):
    name = models.CharField("Название", max_length=120, unique=True)
    slug = models.SlugField("Слаг", unique=True)
    description = models.TextField("Описание", blank=True)
    # ↓ Новое поле
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

    # превью в админке
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

    # медиа
    main_image = models.ImageField(upload_to="store/products/", blank=True, null=True)

    # характеристики и прочие поля
    specs = models.JSONField(default=dict, blank=True)  # произвольные характеристики (ключ-значение)
    tags = ArrayField(models.CharField(max_length=32), blank=True, default=list)

    # совместимость
    compatible_models = models.ManyToManyField(CarModel, blank=True, related_name="compatible_products")

    # SEO/мета
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
            base = slugify(self.name)
            self.slug = base
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("store:product", kwargs={"slug": self.slug})


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="store/products/gallery/")
    alt = models.CharField(max_length=140, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]


class Order(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        REVIEW = "review", "In review"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW)

    # контактные данные
    customer_name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True)

    # информация об авто (для проверки совместимости)
    vehicle_make = models.CharField(max_length=64, blank=True)
    vehicle_model = models.CharField(max_length=64, blank=True)
    vehicle_year = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # кто создал (если клиент авторизован)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return f"Order #{self.pk} — {self.customer_name} — {self.get_status_display()}"

    @property
    def total(self):
        return sum([it.subtotal for it in self.items.all()])


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    qty = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    price_at_moment = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def subtotal(self):
        return self.qty * self.price_at_moment
