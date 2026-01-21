from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
import uuid
from django.core.exceptions import ValidationError
from datetime import timedelta, time
import os
from django.utils import timezone
from django.utils.text import slugify
from django.utils.timezone import localtime
from core.validators import clean_phone
from .constants import STAFF_DISPLAY_NAME
from django.conf import settings
from django.db.models import Sum
from django.core.validators import MaxValueValidator, MinValueValidator
from django.templatetags.static import static

from storages.backends.s3boto3 import S3Boto3Storage
# --- 1. ROLES ---
from django.core.files.storage import FileSystemStorage
from django.conf import settings

from storages.backends.s3boto3 import S3Boto3Storage

def _s3_configured() -> bool:
    required = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_STORAGE_BUCKET_NAME",
        "AWS_S3_REGION_NAME",
    ]
    return all(bool(getattr(settings, key, None)) for key in required)

# не инициализируем S3, если он не настроен, чтобы не получать ValueError
try:
    MASTER_PHOTO_STORAGE = S3Boto3Storage() if _s3_configured() else FileSystemStorage()
except Exception:
    MASTER_PHOTO_STORAGE = FileSystemStorage()
class Role(models.Model):
    """
    Represents a role that can be assigned to a user (e.g., Master, Client, Admin).
    """
    name = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return self.name


class CustomUserDisplay(User):
    """
    Proxy model for Django's User to allow customization in admin views and display logic.
    """
    class Meta:
        proxy = True

    def __str__(self):
        full_name = self.get_full_name()
        return full_name if full_name else self.username


class UserRole(models.Model):
    """
    Links a user to a specific role with a timestamp of when the role was assigned.
    """
    user = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'role')

    def __str__(self):
        return f"{self.user} → {self.role.name}"

class ClientSource(models.Model):
    source = models.CharField()

    def __str__(self):
        return f"{self.source}%"

class HowHeard(models.TextChoices):
    GOOGLE = "google", "Google search"
    INSTAGRAM = "instagram", "Instagram"
    FACEBOOK = "facebook", "Facebook"
    TIKTOK = "tiktok", "TikTok"
    FRIEND = "friend", "Friends/Family"
    OTHER = "other", "Other"


class LegalPage(models.Model):
    """
    Simple editable container for legal documents (Terms, Privacy, etc.).
    """
    slug = models.SlugField(max_length=64, unique=True)
    title = models.CharField(max_length=200)
    body = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Legal page"
        verbose_name_plural = "Legal pages"
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        from django.urls import reverse

        if self.slug == "terms-and-conditions":
            return reverse("legal-terms")
        return reverse("legal-page", kwargs={"slug": self.slug})


class FontPreset(models.Model):
    """
    Reusable font definition that can be applied to public-facing pages.
    Supports static assets as well as uploaded font files.
    """

    class FontStyle(models.TextChoices):
        NORMAL = "normal", "Normal"
        ITALIC = "italic", "Italic"

    slug = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=120)
    font_family = models.CharField(
        max_length=120,
        help_text="Primary CSS font-family name (without fallbacks).",
    )
    fallback_stack = models.CharField(
        max_length=255,
        default='system-ui, -apple-system, "Segoe UI", sans-serif',
        help_text="Comma-separated fallbacks appended after the primary family.",
    )
    static_path = models.CharField(
        max_length=255,
        blank=True,
        help_text="Path inside STATIC files, e.g. fonts/Diesel.ttf.",
    )
    font_file = models.FileField(
        upload_to="fonts/",
        blank=True,
        null=True,
        help_text="Optional upload when hosting the font via MEDIA.",
    )
    mime_type = models.CharField(
        max_length=40,
        default="font/ttf",
        help_text="Used for preload links (e.g. font/ttf, font/woff2).",
    )
    font_weight = models.CharField(
        max_length=40,
        default="100 900",
        help_text="Value used in @font-face font-weight (e.g. '400' or '100 900').",
    )
    font_style = models.CharField(
        max_length=20,
        choices=FontStyle.choices,
        default=FontStyle.NORMAL,
    )
    font_display = models.CharField(
        max_length=20,
        default="swap",
        help_text="font-display value used in @font-face.",
    )
    preload = models.BooleanField(
        default=True,
        help_text="Preload tag will be emitted when this font is used on a page.",
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Font preset"
        verbose_name_plural = "Font presets"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    @property
    def url(self) -> str:
        if self.font_file:
            try:
                return self.font_file.url
            except Exception:
                pass
        if self.static_path:
            return static(self.static_path)
        return ""

    @property
    def format_hint(self) -> str:
        if self.mime_type == "font/woff2":
            return "woff2"
        if self.mime_type == "font/woff":
            return "woff"
        if self.mime_type == "font/otf":
            return "opentype"
        return "truetype"

    @property
    def font_stack(self) -> str:
        fallback = (self.fallback_stack or "").strip().rstrip(",")
        fallback_part = f", {fallback}" if fallback else ""
        return f'"{self.font_family}"{fallback_part}'


class PageFontSetting(models.Model):
    """
    Per-page font mapping controllable from the admin UI.
    """

    class Page(models.TextChoices):
        HOME = "home", "Home page"
        BRAKE_SUSPENSION = "brake_suspension", "Brake & Suspension page"
        WHEEL_TIRE_SERVICE = "wheel_tire_service", "Wheel & Tire Service page"
        PERFORMANCE_TUNING = "performance_tuning", "Performance Tuning page"
        ELECTRICAL_WORK = "electrical_work", "Electrical Work page"

    page = models.CharField(
        max_length=80,
        choices=Page.choices,
        unique=True,
        help_text="Page that will consume the configured fonts.",
    )
    body_font = models.ForeignKey(
        FontPreset,
        on_delete=models.PROTECT,
        related_name="body_font_settings",
    )
    heading_font = models.ForeignKey(
        FontPreset,
        on_delete=models.PROTECT,
        related_name="heading_font_settings",
    )
    ui_font = models.ForeignKey(
        FontPreset,
        on_delete=models.PROTECT,
        related_name="ui_font_settings",
        null=True,
        blank=True,
        help_text="Optional override for navigation, buttons, and labels. Defaults to body font.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Page font setting"
        verbose_name_plural = "Page font settings"
        ordering = ("page",)

    def __str__(self) -> str:
        return f"{self.get_page_display()} — body: {self.body_font} / heading: {self.heading_font}"

    @property
    def resolved_ui_font(self) -> FontPreset:
        return self.ui_font or self.body_font

class ProjectJournalQuerySet(models.QuerySet):
    def published(self):
        return self.filter(
            status=self.model.Status.PUBLISHED,
            published_at__isnull=False,
        )


class ProjectJournalEntry(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=180, unique=True)
    headline = models.CharField(
        max_length=220,
        blank=True,
        help_text="Optional hero headline override.",
    )
    excerpt = models.TextField(
        blank=True,
        help_text="Short teaser shown on cards and previews.",
    )
    body = models.TextField()
    cover_image = models.ImageField(upload_to="project-journal/", blank=True, null=True)
    tags = models.CharField(
        max_length=160,
        blank=True,
        help_text="Comma separated list (e.g. detailing,vinyl,wrap).",
    )
    client_name = models.CharField(
        max_length=120,
        blank=True,
        help_text="Displayed as 'Client' on the public page.",
    )
    location = models.CharField(
        max_length=120,
        blank=True,
        help_text="City / facility to boost trust.",
    )
    services = models.CharField(
        max_length=200,
        blank=True,
        help_text="Comma separated services rendered.",
    )
    result_highlight = models.CharField(
        max_length=200,
        blank=True,
        help_text="Single sentence outcome that appears on cards.",
    )
    reading_time = models.PositiveSmallIntegerField(
        default=4,
        validators=[MinValueValidator(1)],
        help_text="Approximate reading time in minutes.",
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    featured = models.BooleanField(default=False)
    published_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProjectJournalQuerySet.as_manager()

    class Meta:
        verbose_name = "Project journal entry"
        verbose_name_plural = "Project journal entries"
        ordering = ("-published_at", "-created_at")

    def __str__(self) -> str:
        return self.title

    @property
    def hero_title(self) -> str:
        return self.headline or self.title

    @property
    def tag_list(self):
        return [tag.strip() for tag in self.tags.split(",") if tag.strip()]

    @property
    def services_list(self):
        return [svc.strip() for svc in self.services.split(",") if svc.strip()]

    @property
    def is_live(self) -> bool:
        return self.status == self.Status.PUBLISHED and self.published_at is not None

    def get_absolute_url(self):
        from django.urls import reverse

        return f"{reverse('project-journal')}#project-{self.slug}"

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)[:160] if self.title else ""
            if not base_slug:
                base_slug = slugify(str(uuid.uuid4()))
            slug_candidate = base_slug
            suffix = 1
            while ProjectJournalEntry.objects.exclude(pk=self.pk).filter(slug=slug_candidate).exists():
                slug_candidate = f"{base_slug}-{suffix}"
                suffix += 1
            self.slug = slug_candidate[:180]

        if self.status == self.Status.PUBLISHED and not self.published_at:
            self.published_at = timezone.now()
        if self.status == self.Status.DRAFT:
            self.published_at = None

        super().save(*args, **kwargs)

class HeroImage(models.Model):
    """
    Configurable hero/cover image for high-visibility marketing sections.
    """
    class Location(models.TextChoices):
        HOME = "home", "Home hero"
        DEALER_STATUS = "dealer-status", "Dealer banner"
        STORE = "store", "Store hero"
        MERCH = "merch", "Merch hero"
        BRAKE_SUSPENSION_HERO = "brake-suspension-hero", "Brake & Suspension hero"
        BRAKE_SUSPENSION_GALLERY_A = "brake-suspension-gallery-a", "Brake & Suspension gallery — top"
        BRAKE_SUSPENSION_GALLERY_B = "brake-suspension-gallery-b", "Brake & Suspension gallery — middle"
        BRAKE_SUSPENSION_GALLERY_C = "brake-suspension-gallery-c", "Brake & Suspension gallery — bottom"
        PERFORMANCE_TUNING_HERO = "performance-tuning-hero", "Performance Tuning hero"
        PERFORMANCE_TUNING_GALLERY_A = "performance-tuning-gallery-a", "Performance Tuning gallery — top"
        PERFORMANCE_TUNING_GALLERY_B = "performance-tuning-gallery-b", "Performance Tuning gallery — middle"
        PERFORMANCE_TUNING_GALLERY_C = "performance-tuning-gallery-c", "Performance Tuning gallery — bottom"
        ELECTRICAL_WORK_HERO = "electrical-work-hero", "Electrical Work hero"
        ELECTRICAL_WORK_GALLERY_A = "electrical-work-gallery-a", "Electrical Work gallery — top"
        ELECTRICAL_WORK_GALLERY_B = "electrical-work-gallery-b", "Electrical Work gallery — middle"
        ELECTRICAL_WORK_GALLERY_C = "electrical-work-gallery-c", "Electrical Work gallery — bottom"

    location = models.CharField(
        "Placement",
        max_length=32,
        choices=Location.choices,
        unique=True,
    )
    title = models.CharField(
        "Internal title",
        max_length=120,
        blank=True,
        help_text="Optional label to help the team identify the asset.",
    )
    image = models.ImageField(
        "Image",
        upload_to="hero/",
        blank=True,
        null=True,
        help_text="Upload a 16:9 image (webp/jpg recommended, ≤ 2MB).",
    )
    alt_text = models.CharField(
        "Alt text",
        max_length=160,
        blank=True,
        help_text="Accessible description shown to screen readers.",
    )
    caption = models.CharField(
        "Caption / disclaimer",
        max_length=160,
        blank=True,
        help_text="Optional short line rendered under the hero image.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hero asset"
        verbose_name_plural = "Hero assets"
        ordering = ["location"]

    def __str__(self) -> str:
        suffix = f" — {self.title}" if self.title else ""
        return f"{self.get_location_display()}{suffix}"

    def image_preview(self):
        if self.image:
            from django.utils.html import format_html
            try:
                return format_html(
                    '<img src="{}" style="height:60px;border-radius:8px;object-fit:cover;">',
                    self.image.url,
                )
            except Exception:
                return "—"
        return "—"
    image_preview.short_description = "Preview"

# ── NEW/UPDATED: Dealer tiers, application, fields на профиле ─────────────────
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.validators import MinLengthValidator


class DealerTier(models.TextChoices):
    NONE = "NONE", "None"
    TIER_5 = "TIER_5", "Dealer 5% tier"
    TIER_10 = "TIER_10", "Dealer 10% tier"
    TIER_15 = "TIER_15", "Dealer 15% tier"


class DealerTierLevel(models.Model):
    """
    Editable tier configuration accessible from the admin panel.
    Allows ops to tune names, minimum spend, and discount percent without code changes.
    """
    code = models.CharField(
        "Code",
        max_length=16,
        choices=DealerTier.choices,
        unique=True,
    )
    label = models.CharField("Label", max_length=120)
    discount_percent = models.PositiveIntegerField("Discount percent", default=5)
    minimum_spend = models.PositiveIntegerField(
        f"Minimum lifetime spend ({settings.DEFAULT_CURRENCY_CODE})",
        default=0,
        help_text=f"Required lifetime spend in {settings.DEFAULT_CURRENCY_CODE} to qualify for this tier.",
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    description = models.CharField(
        "Short description",
        max_length=200,
        blank=True,
        help_text="Optional helper text shown in the dealer portal.",
    )

    class Meta:
        verbose_name = "Dealer tier level"
        verbose_name_plural = "Dealer tier levels"
        ordering = ["minimum_spend", "sort_order", "code"]

    def __str__(self) -> str:
        return f"{self.label} ({self.discount_percent}% off)"

DEALER_THRESHOLDS = {
    DealerTier.TIER_5: 1000,
    DealerTier.TIER_10: 5000,
    DealerTier.TIER_15: 20000,
}
DEALER_DISCOUNTS = {
    DealerTier.TIER_5: 5,
    DealerTier.TIER_10: 10,
    DealerTier.TIER_15: 15,
}

class DealerApplication(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dealer_application",
        verbose_name="User",
    )
    business_name = models.CharField("Business name", max_length=128)
    website = models.URLField("Website", blank=True)
    phone = models.CharField("Phone", max_length=32, validators=[MinLengthValidator(5)])
    notes = models.TextField("Notes", blank=True)
    preferred_tier = models.CharField(
        "Preferred tier",
        max_length=16,
        choices=DealerTier.choices,
        default=DealerTier.TIER_5,
        help_text="Requested tier based on projected volume.",
    )
    assigned_tier = models.CharField(
        "Assigned tier",
        max_length=16,
        choices=DealerTier.choices,
        blank=True,
        help_text="Tier granted by the admin team when approving the account.",
    )
    internal_note = models.TextField(
        "Internal note",
        blank=True,
        help_text="Private note for the review team (not shared with the dealer).",
    )
    status = models.CharField(
        "Status", max_length=16, choices=Status.choices, default=Status.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="dealer_reviews",
        verbose_name="Reviewed by",
    )

    class Meta:
        verbose_name = "Dealer Application"
        verbose_name_plural = "Dealer Applications"
        ordering = ["-created_at"]

    def resolved_tier(self) -> str:
        """
        Returns the tier that should be applied to the user profile.
        Admin-selected tier wins over the applicant's preference.
        """
        return self.assigned_tier or self.preferred_tier or DealerTier.NONE

    def approve(self, admin_user, *, tier=None):
        if tier:
            self.assigned_tier = tier
        self.status = self.Status.APPROVED
        self.reviewed_at = timezone.now()
        self.reviewed_by = admin_user
        self.save(update_fields=["status", "reviewed_at", "reviewed_by", "assigned_tier"])
        final_tier = self.resolved_tier()
        # Обновим профиль пользователя
        up = getattr(self.user, "userprofile", None)
        if up:
            up.is_dealer = True
            if final_tier and final_tier != DealerTier.NONE:
                up.dealer_tier = final_tier
            else:
                # tier будет выставляться на основании total_spent (см. метод ниже)
                up.recompute_dealer_tier()
            up.dealer_since = up.dealer_since or timezone.now()
            up.save(update_fields=["is_dealer", "dealer_tier", "dealer_since"])

    def reject(self, admin_user):
        self.status = self.Status.REJECTED
        self.reviewed_at = timezone.now()
        self.reviewed_by = admin_user
        self.assigned_tier = ""
        self.save(update_fields=["status", "reviewed_at", "reviewed_by", "assigned_tier"])



class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="userprofile")

    phone = models.CharField(max_length=32, unique=True)
    birth_date = models.DateField(null=True, blank=True)
    is_dealer = models.BooleanField("Is dealer", default=False)
    dealer_tier = models.CharField(
        "Dealer tier",
        max_length=16,
        choices=DealerTier.choices,
        default=DealerTier.NONE,
    )
    dealer_since = models.DateTimeField("Dealer since", null=True, blank=True)

    # === NEW ===
    address = models.TextField(blank=True)                         # одна строка/много строк — на твой вкус
    email_marketing_consent = models.BooleanField(default=False)   # согласие на рассылки
    email_marketing_consented_at = models.DateTimeField(null=True, blank=True)
    how_heard = models.CharField(max_length=32, choices=HowHeard.choices, blank=True)

    def set_marketing_consent(self, value: bool):
        """Convenience helper: switches consent flag and timestamp in sync."""
        if value and not self.email_marketing_consent:
            self.email_marketing_consent = True
            self.email_marketing_consented_at = timezone.now()
        elif not value and self.email_marketing_consent:
            self.email_marketing_consent = False
            self.email_marketing_consented_at = None
            
    def __str__(self):
        return f"{self.user} Profile"
    
    



   

    def total_spent_cad(self) -> float:
        """
        Total spent by the user in CAD:
        - Sum of all Payment.amount for appointments where client=self.user
        - PLUS sum of service.base_price for paid appointments that have NO payments
        (to avoid double counting).
        """
        try:
            from core.models import Payment, Appointment, PaymentStatus
        except Exception:
            return 0.0

        # 1) Sum of all payments
        payments_total = Payment.objects.filter(
            appointment__client=self.user
        ).aggregate(s=Sum("amount"))["s"] or 0

        # 2) Paid appointments that have NO payments
        paid_names = {"Paid", "Completed", "Settled", "paid", "completed", "settled"}
        paid_statuses = PaymentStatus.objects.filter(name__in=paid_names)

        appts_without_payments_total = Appointment.objects.filter(
            client=self.user,
            payment_status__in=paid_statuses,
            payment__isnull=True,  # no payments linked
        ).aggregate(s=Sum("service__base_price"))["s"] or 0

        return float(payments_total) + float(appts_without_payments_total)


    def _tier_levels_queryset(self):
        return DealerTierLevel.objects.filter(is_active=True).order_by("minimum_spend", "sort_order", "code")

    def get_dealer_tier_level(self):
        cache_attr = "_dealer_tier_level_cache"
        cached = getattr(self, cache_attr, None)
        if cached and cached.code == self.dealer_tier:
            return cached
        try:
            level = self._tier_levels_queryset().filter(code=self.dealer_tier).first()
        except Exception:
            level = None
        setattr(self, cache_attr, level)
        return level

    def recompute_dealer_tier(self) -> None:
        spent = Decimal(str(self.total_spent_cad()))
        try:
            tiers = list(self._tier_levels_queryset())
        except Exception:
            tiers = []
        chosen = DealerTier.NONE
        fallback = DealerTier.NONE

        if tiers:
            for level in tiers:
                if spent >= Decimal(level.minimum_spend):
                    chosen = level.code
                else:
                    break
            level_match = next((lvl for lvl in tiers if lvl.code == chosen), None)
            setattr(self, "_dealer_tier_level_cache", level_match)
        else:
            # Fallback to static thresholds if no rows configured in DB.
            fallback = DealerTier.NONE
            if spent >= Decimal(DEALER_THRESHOLDS[DealerTier.TIER_15]):
                fallback = DealerTier.TIER_15
            elif spent >= Decimal(DEALER_THRESHOLDS[DealerTier.TIER_10]):
                fallback = DealerTier.TIER_10
            elif spent >= Decimal(DEALER_THRESHOLDS[DealerTier.TIER_5]):
                fallback = DealerTier.TIER_5
            chosen = fallback

        self.dealer_tier = chosen  # do NOT flip is_dealer here





    @property
    def dealer_discount_percent(self) -> int:
        level = self.get_dealer_tier_level()
        if level:
            return level.discount_percent
        return DEALER_DISCOUNTS.get(self.dealer_tier, 0)

# --- 2. SERVICES ---

class ServiceCategory(models.Model):
    """
    Represents a service offered in the system (e.g., haircut, massage).
    """
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class PrepaymentOption(models.Model):
    """
    Defines available prepayment percentage options.
    """
    percent = models.IntegerField()

    def __str__(self):
        return f"{self.percent}%"

# imports должны уже быть в файле:
# import uuid
# from decimal import Decimal
# from django.utils import timezone
# from django.db import models
# (и ваши ServiceCategory, PrepaymentOption)

class Service(models.Model):
    """
    Represents a service offered in the system (e.g., haircut, massage).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    category = models.ForeignKey(ServiceCategory, on_delete=models.CASCADE, blank=True, null=True)
    prepayment_option = models.ForeignKey(PrepaymentOption, on_delete=models.CASCADE, blank=True, null=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    contact_for_estimate = models.BooleanField(
        "Contact for estimate",
        default=False,
        help_text='Display “Contact for estimate” instead of a fixed price on the storefront.',
    )
    estimate_from_price = models.DecimalField(
        "Starting from",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text='Optional “From $X” hint shown next to the contact label.',
    )
    duration_min = models.IntegerField()
    extra_time_min = models.IntegerField(null=True, blank=True)

    # NEW: cover image for service card
    image = models.ImageField(
        "Image",
        upload_to="services/",
        blank=True,
        null=True,
        help_text="Upload a service cover image (recommended ratio ~16:9).",
    )

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.contact_for_estimate and self.estimate_from_price is not None and self.estimate_from_price <= 0:
            raise ValidationError({"estimate_from_price": "Starting price must be greater than zero."})

    def base_price_amount(self) -> Decimal:
        """
        Safe accessor that always returns a quantized Decimal.
        """
        value = self.base_price
        if value is None:
            return Decimal("0.00")
        return Decimal(value).quantize(Decimal("0.01"))

    def has_public_price(self) -> bool:
        return not self.contact_for_estimate and self.base_price is not None

    # Admin inline preview (safe to call in admin)
    def image_preview(self):
        from django.utils.html import format_html
        if getattr(self, "image", None):
            try:
                return format_html('<img src="{}" style="height:60px;border-radius:8px">', self.image.url)
            except Exception:
                return "—"
        return "—"
    image_preview.short_description = "Preview"

    def get_active_discount(self):
        today = timezone.now().date()
        return self.discounts.filter(start_date__lte=today, end_date__gte=today).first()

    def get_discounted_price(self):
        """
        Call instead of price to get discounted price or base_price if discount is not set
        """
        discount = self.get_active_discount()
        base_amount = self.base_price_amount()
        if discount and not self.contact_for_estimate:
            discount_multiplier = Decimal(1) - (Decimal(discount.discount_percent) / Decimal(100))
            return (base_amount * discount_multiplier).quantize(Decimal('0.01'))
        return base_amount

    def public_price(self):
        """
        Returns the amount that should be shown to customers, or None if the service is contact-only.
        """
        if not self.has_public_price():
            return None
        discount = self.get_active_discount()
        if discount:
            return self.get_discounted_price()
        return self.base_price_amount()


class MasterRoom(models.Model):
    """
    Rooms where Master will operate
    """
    room = models.CharField(max_length=20)

    def __str__(self):
        return self.room

    class Meta:
        verbose_name = f"{STAFF_DISPLAY_NAME} Room"
        verbose_name_plural = f"{STAFF_DISPLAY_NAME} Rooms"

class MasterProfile(models.Model):
    """
    Дополнительная информация о мастере: профессия, график работы, цвет и т.д.
    """
    user = models.OneToOneField(CustomUserDisplay, on_delete=models.CASCADE, related_name="master_profile")
    profession = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    room = models.ForeignKey(MasterRoom, on_delete=models.CASCADE, blank=True, null=True)
    work_start = models.TimeField(default="08:00")
    work_end = models.TimeField(default="21:00")
    photo = models.ImageField(upload_to="masters/", storage=MASTER_PHOTO_STORAGE, blank=True, null=True)

    def save(self, *args, **kwargs):
        """
        Persist profile changes and guarantee the linked user carries the Master role.
        """
        response = super().save(*args, **kwargs)
        self._ensure_master_role()
        return response

    def _ensure_master_role(self):
        if not self.user_id:
            return
        from core.utils import assign_role
        master_role, _ = Role.objects.get_or_create(name="Master")
        assign_role(self.user, master_role)

    def __str__(self):
        return f"{self.user.get_full_name()}"

    class Meta:
        verbose_name = f"{STAFF_DISPLAY_NAME} Profile"
        verbose_name_plural = f"{STAFF_DISPLAY_NAME} Profiles"

class ServiceMaster(models.Model):
    """
    Connects a specific service with a master who can perform it.
    """
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    master = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.master} → {self.service.name}"

    class Meta:
        verbose_name = f"{STAFF_DISPLAY_NAME} Service Assignment"
        verbose_name_plural = f"{STAFF_DISPLAY_NAME} Service Assignments"

# --- 3. APPOINTMENTS ---

class AppointmentStatus(models.Model):
    """
    Statuses an appointment can have (e.g., Confirmed, Cancelled).
    """
    name = models.CharField(max_length=20)

    def __str__(self):
        return self.name


class PaymentStatus(models.Model):
    """
    Describes the status of a payment (e.g., Paid, Pending).
    """
    name = models.CharField(max_length=20)

    def __str__(self):
        return self.name


class Appointment(models.Model):
    """
    Represents a scheduled appointment between a client and a master for a service.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        CustomUserDisplay,
        on_delete=models.CASCADE,
        related_name='appointments_as_client',
        null=True,
        blank=True,
    )
    contact_name = models.CharField(max_length=120, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    master = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE, related_name='appointments_as_master')
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    start_time = models.DateTimeField()
    payment_status = models.ForeignKey(PaymentStatus, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        formatted = localtime(self.start_time).strftime("%Y-%m-%d %H:%M")
        client_name = self.contact_name
        if not client_name and self.client:
            client_name = self.client.get_full_name() or self.client.username
        client_name = client_name or "Guest"
        return f"{client_name} for {self.service} at {formatted}"

    def clean(self):
        if self.start_time and self.start_time.time() > time(23, 59):
            raise ValidationError({
                "start_time": "Start time cannot be later than 23:59."
            })

        # Остальная логика…
        if not self.master or not self.service or not self.start_time:
            return

        # Контактные данные: либо есть клиент, либо все поля заполнены
        if not self.client:
            err = {}
            if not self.contact_name:
                err["contact_name"] = "Name is required for guest bookings."
            if not self.contact_email:
                err["contact_email"] = "Email is required for guest bookings."
            if not self.contact_phone:
                err["contact_phone"] = "Phone is required for guest bookings."
            if err:
                raise ValidationError(err)
        if self.contact_phone:
            try:
                clean_phone(self.contact_phone)
            except ValidationError as exc:
                raise ValidationError({"contact_phone": exc.messages[0]})

        cancelled_status = AppointmentStatus.objects.filter(name="Cancelled").first()
        # Проверка на пересечение с другими записями
        overlapping = Appointment.objects.filter(
            master=self.master,
            start_time__lt=self.start_time + timedelta(minutes=self.service.duration_min),
            start_time__gte=self.start_time - timedelta(hours=3)
        ).exclude(id=self.id)

        overlapping = overlapping.exclude(
            appointmentstatushistory__status=cancelled_status
        )

        this_end = self.start_time + timedelta(minutes=self.service.duration_min)
        for appt in overlapping:
            other_end = appt.start_time + timedelta(minutes=appt.service.duration_min)
            if self.start_time < other_end and this_end > appt.start_time:
                raise ValidationError({
                    "start_time": "This appointment overlaps with another appointment for the same tech."
                })

            # --- 🔒 Проверка пересечения по комнате ---
        master_profile = getattr(self.master, "master_profile", None)
        if master_profile and master_profile.room:
            overlapping_room = Appointment.objects.filter(
                master__master_profile__room=master_profile.room,
                start_time__lt=this_end,
                start_time__gte=self.start_time - timedelta(hours=3)
            ).exclude(id=self.id)

            for appt in overlapping_room:
                appt_end = appt.start_time + timedelta(minutes=appt.service.duration_min)
                if self.start_time < appt_end and this_end > appt.start_time:
                    raise ValidationError({
                        "start_time": f"Room '{master_profile.room}' is occupied at this time."
                    })
        # Проверка на отпуск / отгулы
        unavailable_periods = MasterAvailability.objects.filter(master=self.master)

        for period in unavailable_periods:
            if self.start_time < period.end_time and this_end > period.start_time:
                raise ValidationError({"start_time": "This appointment falls within the tech's time off or vacation."})

        master_profile = getattr(self.master, "master_profile", None)
        if master_profile and self.start_time:
            local_start_dt = localtime(self.start_time)

            # длительность услуги с учётом extra_time_min
            extra_min = self.service.extra_time_min or 0
            total_minutes = self.service.duration_min + extra_min
            local_end_dt = local_start_dt + timedelta(minutes=total_minutes)

            # рабочее окно мастера на ДАННУЮ дату
            ws: time = master_profile.work_start
            we: time = master_profile.work_end

            work_start_dt = local_start_dt.replace(hour=ws.hour, minute=ws.minute, second=0, microsecond=0)
            work_end_dt   = local_start_dt.replace(hour=we.hour, minute=we.minute, second=0, microsecond=0)

            # Если смена «через полночь» (например, 22:00–06:00), расширяем конец на следующий день
            if work_end_dt <= work_start_dt:
                work_end_dt += timedelta(days=1)
                # если встреча начинается после полуночи (т.е. до work_end), тоже считаем её «следующим днём»
                if local_end_dt <= work_start_dt:
                    local_end_dt += timedelta(days=1)
                if local_start_dt <= work_start_dt:
                    local_start_dt += timedelta(days=1)

            # 1) старт раньше начала смены
            if local_start_dt < work_start_dt:
                raise ValidationError({
                    "start_time": f"Start time ({local_start_dt.strftime('%H:%M')}) earlier than tech's shift starts "
                                  f"({work_start_dt.strftime('%H:%M')})."
                })

            # 2) конец позже конца смены
            if local_end_dt > work_end_dt:
                raise ValidationError({
                    "start_time": f"The appointment ends at ({local_end_dt.strftime('%H:%M')}) which is later than tech's end of shift "
                                  f"({work_end_dt.strftime('%H:%M')})."
                })

class AppointmentStatusHistory(models.Model):
    """
    Tracks status changes for appointments, including who made the change and when.
    """
    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE)
    status = models.ForeignKey(AppointmentStatus, on_delete=models.CASCADE)
    set_by = models.ForeignKey(
        CustomUserDisplay,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    set_at = models.DateTimeField(auto_now_add=True)

# --- 4. PAYMENTS ---

class PaymentMethod(models.Model):
    """
    Represents a method of payment (e.g., Credit Card, Cash).
    """
    name = models.CharField(max_length=20)

    def __str__(self):
        return self.name


class Payment(models.Model):
    """
    Stores payment records for appointments and store orders.
    """
    class PaymentMode(models.TextChoices):
        FULL = ("full", "Paid in full")
        DEPOSIT_50 = ("deposit_50", "50% deposit")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Linked appointment, if this payment came from a booking.",
    )
    order = models.ForeignKey(
        "store.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
        help_text="Linked store order, if this payment came from checkout.",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(
        max_length=8,
        default=getattr(settings, "DEFAULT_CURRENCY_CODE", "CAD"),
    )
    method = models.ForeignKey(PaymentMethod, on_delete=models.CASCADE)
    payment_mode = models.CharField(
        max_length=20,
        choices=PaymentMode.choices,
        default=PaymentMode.FULL,
        db_index=True,
    )
    balance_due = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Outstanding balance (e.g., when only a deposit was collected).",
    )
    processor = models.CharField(max_length=32, blank=True, default="")
    processor_payment_id = models.CharField(max_length=140, blank=True, default="")
    receipt_url = models.URLField(blank=True, default="")
    card_brand = models.CharField(max_length=40, blank=True, default="")
    card_last4 = models.CharField(max_length=8, blank=True, default="")
    fee_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Processor fee collected for this payment, if available.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        prefix = "Payment"
        if self.order_id:
            prefix = f"Order #{self.order_id}"
        elif self.appointment_id:
            prefix = f"Appt {self.appointment}"
        return f"{prefix} — {self.amount} {self.currency}"

    @property
    def is_deposit(self) -> bool:
        return self.payment_mode == self.PaymentMode.DEPOSIT_50

# --- 5. PREPAYMENTS ---


class AppointmentPrepayment(models.Model):
    """
    Links a prepayment option to a specific appointment.
    """
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE)
    option = models.ForeignKey(PrepaymentOption, on_delete=models.CASCADE)

# --- 6. FILES ---

class ClientFile(models.Model):
    """
    Represents a file uploaded for a user, such as a document or image.
    """
    USER = 'user'
    ADMIN = 'admin'

    OWNER_CHOICES = [
        (USER, 'User'),
        (ADMIN, 'Admin'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)
    file = models.FileField(
        upload_to='client_files/',
        storage=MASTER_PHOTO_STORAGE,
        help_text="Uploaded file stored in the configured media storage."
    )
    file_type = models.CharField(max_length=50, editable=False, blank=True)
    file_size = models.PositiveIntegerField(null=True, blank=True, help_text="Size in bytes for quick display.")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.CharField(
        max_length=10,
        choices=OWNER_CHOICES,
        default=USER,
        help_text="Who uploaded the file: admin or user"
    )

    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional description (e.g., 'Form before procedure')"
    )

    def save(self, *args, **kwargs):
        if self.file:
            if not self.file_type:
                _, extension = os.path.splitext(self.file.name)
                self.file_type = extension.lower().lstrip('.')
            try:
                self.file_size = self.file.size
            except Exception:
                # leave previous value if storage can't provide size
                self.file_size = self.file_size or None
        super().save(*args, **kwargs)

    @property
    def filename(self):
        if not self.file:
            return ""
        return os.path.basename(self.file.name)

    @property
    def is_image(self) -> bool:
        ext = (self.file_type or "").lower()
        return ext in {"jpg", "jpeg", "png", "webp", "gif", "heic", "bmp"}

# --- 7. NOTIFICATIONS ---

class Notification(models.Model):
    """
    Represents a notification sent to a user regarding an appointment.
    Supports email and SMS channels.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)
    appointment = models.ForeignKey(Appointment, on_delete=models.SET_NULL, null=True, blank=True)
    channel = models.CharField(max_length=10, choices=[('email', 'Email'), ('sms', 'SMS')])
    message = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        """
        Triggers message sending based on the selected channel (email or SMS).
        """
        is_new = self._state.adding
        super().save(*args, **kwargs)

        if is_new:
            if self.channel == 'email':
                self.send_email()
            elif self.channel == 'sms':
                self.send_sms()

    def send_email(self):
        """
        Stub: logic to send an email message to the user.
        """
        print(f"[EMAIL] To {self.user}: {self.message}")

    def send_sms(self):
        """
        Stub: logic to send an SMS message to the user.
        """
        print(f"[SMS] To {self.user}: {self.message}")

# --- 8. MASTERS ---


class MasterAvailability(models.Model):
    VACATION = 'vacation'
    LUNCH = 'lunch'
    BREAK = 'break'

    REASON_CHOICES = [
        (VACATION, 'Vacation'),
        (LUNCH, 'Lunch'),
        (BREAK, 'Break'),
    ]

    master = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    reason = models.CharField(
        max_length=20,
        choices=REASON_CHOICES,
        default=VACATION,
        help_text="Reason for time off"
    )

    class Meta:
        verbose_name = "Time Off / Vacation"
        verbose_name_plural = "Time Offs / Vacations"

    def __str__(self):
        return f"{self.master} → {self.get_reason_display()} from {self.start_time} to {self.end_time}"

    def clean(self):
        super().clean()

        if not self.master or not self.start_time or not self.end_time:
            return  # Не валидируем, если что-то не заполнено

        # Найдём все записи мастера, которые пересекаются с отпуском
        overlapping_appointments = Appointment.objects.filter(
            master=self.master,
            start_time__lt=self.end_time,
            start_time__gte=self.start_time - timedelta(hours=3)  # захватываем буфер
        )

        for appt in overlapping_appointments:
            appt_end = appt.start_time + timedelta(minutes=appt.service.duration_min)
            if self.start_time < appt_end and self.end_time > appt.start_time:
                raise ValidationError({
                    "start_time": "Vacation overlaps with existing appointments",
                })


class ClientReview(models.Model):
    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.CASCADE,
        related_name='review',
        help_text="One review per one appointment"
    )
    rating = models.PositiveSmallIntegerField(
        choices=[(i, f"{i} ★") for i in range(1, 6)],
        help_text="Rating 1 to 5"
    )
    comment = models.TextField(blank=True, help_text="Not obligatory text comment")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Review {self.rating}★ for {self.appointment}"

    class Meta:
        verbose_name = "Client Review"
        verbose_name_plural = "Client Reviews"


class ServiceDiscount(models.Model):
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='discounts')
    discount_percent = models.PositiveIntegerField(help_text="Percent of discount")
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        verbose_name = "Service Discount"
        verbose_name_plural = "Service Discounts"
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.discount_percent}% off on {self.service.name} ({self.start_date} – {self.end_date})"

    def is_active(self):
        today = timezone.now().date()
        return self.start_date <= today <= self.end_date


class PromoCode(models.Model):
    code = models.CharField(max_length=20, unique=True)
    discount_percent = models.PositiveIntegerField(help_text="discount in percents(0-100)")
    active = models.BooleanField(default=True)
    start_date = models.DateField()
    end_date = models.DateField()
    applicable_services = models.ManyToManyField(Service, blank=True, help_text="leave empty to apply to all services")

    def is_valid_for(self, service, today=None):
        today = today or timezone.now().date()
        return (
                self.active and
                self.start_date <= today <= self.end_date and
                (self.applicable_services.count() == 0 or self.applicable_services.filter(pk=service.pk).exists())
        )

    def __str__(self):
        return self.code

class AppointmentPromoCode(models.Model):
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE)
    promocode = models.ForeignKey(PromoCode, on_delete=models.CASCADE)

    def clean(self):
        if self.promocode.end_date < timezone.now().date():
            raise ValidationError({
                "promocode": "This promocode is expired."
            })
        now = timezone.now()
        discounts = ServiceDiscount.objects.filter(
            service=self.appointment.service,
            start_date__lte=now,
            end_date__gte=now
        ).exists()
        if discounts:
            raise ValidationError({
                "promocode": "This Service already has a discount. Promocode can't be applied"
            })


class SiteNoticeSignup(models.Model):
    """
    Captures popup email signups so follow-up emails can be scheduled.
    """

    email = models.EmailField()
    welcome_code = models.CharField(max_length=40)
    welcome_sent_at = models.DateTimeField(default=timezone.now)
    followup_2_sent_at = models.DateTimeField(null=True, blank=True)
    followup_3_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Site notice signup"
        verbose_name_plural = "Site notice signups"
        indexes = [
            models.Index(fields=["welcome_sent_at"]),
            models.Index(fields=["followup_2_sent_at"]),
            models.Index(fields=["followup_3_sent_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.email} ({self.welcome_code})"


class ServiceLead(models.Model):
    """
    Inbound lead captured from public service landing pages.
    """

    class Status(models.TextChoices):
        NEW = ("new", "New")
        CONTACTED = ("contacted", "Contacted")
        CLOSED = ("closed", "Closed")

    class SourcePage(models.TextChoices):
        GENERAL_REQUEST = ("general_request", "General request")
        PERFORMANCE_TUNING = ("performance_tuning", "Performance tuning")
        ELECTRICAL_WORK = ("electrical_work", "Electrical work")
        BRAKE_SUSPENSION = ("brake_suspension", "Brake & suspension")
        WHEEL_TIRE_SERVICE = ("wheel_tire_service", "Wheel & tire service")
        OTHER = ("other", "Other")

    full_name = models.CharField(max_length=160)
    phone = models.CharField(max_length=40)
    email = models.EmailField(blank=True)
    vehicle = models.CharField(max_length=160, blank=True)
    service_needed = models.CharField(max_length=160)
    notes = models.TextField(blank=True)
    source_page = models.CharField(
        max_length=64,
        choices=SourcePage.choices,
        default=SourcePage.OTHER,
        db_index=True,
    )
    source_url = models.URLField(
        max_length=600,
        blank=True,
        help_text="Original URL the lead submitted from.",
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
        ordering = ("-created_at",)
        verbose_name = "Service lead"
        verbose_name_plural = "Service leads"

    def __str__(self) -> str:
        return f"{self.full_name} — {self.service_needed}"


class LandingPageReview(models.Model):
    """
    Marketing review snippets shown on specific landing pages.
    """

    class Page(models.TextChoices):
        PERFORMANCE_TUNING = ("performance_tuning", "Performance tuning")
        ELECTRICAL_WORK = ("electrical_work", "Electrical work")
        BRAKE_SUSPENSION = ("brake_suspension", "Brake & suspension")

    page = models.CharField(
        max_length=64,
        choices=Page.choices,
        db_index=True,
        help_text="Landing page that will display this review.",
    )
    reviewer_name = models.CharField(max_length=160)
    reviewer_title = models.CharField(
        max_length=160,
        blank=True,
        help_text="Optional label such as vehicle, platform, or role.",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Rating between 1 (worst) and 5 (best).",
    )
    quote = models.TextField(help_text="Review text that will be shown publicly.")
    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Lower numbers appear first on the landing page.",
    )
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("page", "display_order", "-created_at")
        verbose_name = "Landing page review"
        verbose_name_plural = "Landing page reviews"

    def __str__(self) -> str:
        return f"{self.get_page_display()}: {self.rating}★ by {self.reviewer_name}"

    @property
    def star_range(self):
        return range(self.rating or 0)


class VisitorSession(models.Model):
    """
    Persistent visitor session that lets us tie anonymous requests, account data
    and downstream engagement signals together.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_key = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(
        CustomUserDisplay,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analytics_sessions",
    )
    user_email_snapshot = models.EmailField(blank=True)
    user_name_snapshot = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    referrer = models.URLField(max_length=512, blank=True)
    landing_path = models.CharField(max_length=512, blank=True)
    landing_query = models.CharField(max_length=512, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-last_seen_at",)

    def __str__(self) -> str:
        label = self.user_name_snapshot or (self.user.get_full_name() if self.user else "")
        return label or f"Visitor {self.session_key}"


class PageView(models.Model):
    """
    Single logical view of a page (including duration updates while the tab stays open).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        VisitorSession,
        on_delete=models.CASCADE,
        related_name="page_views",
    )
    user = models.ForeignKey(
        CustomUserDisplay,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="page_views",
    )
    page_instance_id = models.CharField(
        max_length=50,
        unique=True,
        help_text="Client-generated identifier used to keep updates idempotent.",
    )
    path = models.CharField(max_length=512)
    full_path = models.CharField(max_length=768, blank=True)
    page_title = models.CharField(max_length=255, blank=True)
    referrer = models.CharField(max_length=512, blank=True)
    started_at = models.DateTimeField()
    duration_ms = models.PositiveIntegerField(default=0)
    timezone_offset = models.SmallIntegerField(
        default=0,
        help_text="Client timezone offset in minutes (UTC = 0).",
    )
    viewport_width = models.PositiveIntegerField(null=True, blank=True)
    viewport_height = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-started_at",)

    def __str__(self) -> str:
        return f"{self.path} ({self.duration_ms} ms)"

    @property
    def duration_seconds(self) -> float:
        return round(self.duration_ms / 1000, 2)
