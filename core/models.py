from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
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
from django.contrib.staticfiles import finders

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
    notify_on_new_appointment = models.BooleanField(default=False)
    notify_on_new_order = models.BooleanField(default=False)
    notify_on_service_lead = models.BooleanField(default=False)
    notify_on_fitment_request = models.BooleanField(default=False)
    notify_on_site_notice_signup = models.BooleanField(default=False)
    notify_on_order_review_request = models.BooleanField(default=False)

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


# --- ADMIN SIDEBAR ---


class AdminSidebarSeen(models.Model):
    """
    Tracks when a staff user last opened an admin model page.
    Used to render per-user sidebar notification dots.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="admin_sidebar_seen",
    )
    app_label = models.CharField(max_length=100)
    model_name = models.CharField(max_length=100)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("user", "app_label", "model_name")
        indexes = [
            models.Index(fields=["user", "app_label", "model_name"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} → {self.app_label}.{self.model_name}"


class AdminLoginBranding(models.Model):
    """
    Stores logo assets for the admin login screen.
    """
    singleton_id = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    login_logo = models.ImageField(
        upload_to="admin/branding/",
        blank=True,
        null=True,
        help_text="Logo shown on the admin login screen.",
    )
    login_logo_dark = models.ImageField(
        upload_to="admin/branding/",
        blank=True,
        null=True,
        help_text="Optional dark mode logo for the admin login screen.",
    )
    login_logo_alt = models.CharField(
        max_length=120,
        default="Admin logo",
        help_text="Accessible alt text for the login logo.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Admin login branding"
        verbose_name_plural = "Admin login branding"
        ordering = ("singleton_id",)

    def __str__(self) -> str:
        return "Admin login branding"

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_id=1)
        return obj


class ClientUiCheckRun(models.Model):
    """
    Stores results of automated client UI checks.
    """

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    class Trigger(models.TextChoices):
        AUTO = "auto", "Auto"
        MANUAL = "manual", "Manual"

    trigger = models.CharField(max_length=12, choices=Trigger.choices, default=Trigger.AUTO)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)

    total_pages = models.PositiveIntegerField(default=0)
    total_links = models.PositiveIntegerField(default=0)
    total_forms = models.PositiveIntegerField(default=0)
    total_buttons = models.PositiveIntegerField(default=0)
    failures_count = models.PositiveIntegerField(default=0)
    warnings_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)

    summary = models.TextField(blank=True)
    report = models.JSONField(blank=True, default=dict)
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ui_check_runs",
    )

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "Client UI check"
        verbose_name_plural = "Client UI checks"

    def __str__(self) -> str:
        return f"{self.started_at:%Y-%m-%d %H:%M} · {self.get_status_display()}"

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


class BackgroundAsset(models.Model):
    """
    Reusable background image that can be applied across multiple pages.
    """
    title = models.CharField(max_length=120, blank=True)
    image = models.ImageField(
        upload_to="backgrounds/",
        blank=True,
        null=True,
        help_text="Upload a background image (webp/jpg recommended).",
    )
    alt_text = models.CharField(
        max_length=160,
        blank=True,
        help_text="Accessible description shown to screen readers.",
    )
    caption = models.CharField(
        max_length=160,
        blank=True,
        help_text="Optional short line rendered under the hero image.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Background asset"
        verbose_name_plural = "Background assets"
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.title or f"Background {self.pk}"

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


class SiteBackgroundSettings(models.Model):
    """
    Singleton for controlling a global background applied across the site.
    """
    singleton_id = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    default_background = models.ForeignKey(
        BackgroundAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="site_defaults",
        help_text="If set, overrides page-specific hero backgrounds across the site.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Site background"
        verbose_name_plural = "Site backgrounds"
        ordering = ("singleton_id",)

    def __str__(self) -> str:
        return "Site background"

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_id=1)
        return obj


class PageCopyDraft(models.Model):
    """
    Stores autosaved draft edits for PageCopy models before publishing.
    """
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Page copy draft"
        verbose_name_plural = "Page copy drafts"
        unique_together = ("content_type", "object_id")

    def __str__(self) -> str:
        return f"Draft for {self.content_type} #{self.object_id}"

    @classmethod
    def for_instance(cls, instance):
        if not instance or not getattr(instance, "pk", None):
            return None
        content_type = ContentType.objects.get_for_model(instance.__class__)
        draft, _ = cls.objects.get_or_create(content_type=content_type, object_id=instance.pk)
        return draft

    def apply_to_instance(self, instance):
        if not instance:
            return instance
        payload = self.data or {}
        for field_name, value in payload.items():
            try:
                field_obj = instance._meta.get_field(field_name)
            except Exception:
                continue
            if isinstance(field_obj, (models.CharField, models.TextField)):
                setattr(instance, field_name, value)
        return instance


class PageSection(models.Model):
    """
    Dynamic page builder section tied to a PageCopy model.
    """

    class SectionType(models.TextChoices):
        HERO = "hero", "Hero"
        TEXT = "text", "Text"
        IMAGE = "image", "Image"
        GALLERY = "gallery", "Gallery"
        FAQ = "faq", "FAQ"
        CUSTOM = "custom", "Custom HTML"

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    pagecopy = GenericForeignKey("content_type", "object_id")
    section_type = models.CharField(max_length=40, choices=SectionType.choices)
    order = models.PositiveIntegerField(default=0)
    config = models.JSONField(default=dict, blank=True)
    background_image = models.ForeignKey(
        BackgroundAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="page_sections",
    )
    background_color = models.CharField(
        max_length=32,
        blank=True,
        help_text="Optional CSS color (hex/rgb) for the section background.",
    )
    overlay_color = models.CharField(
        max_length=32,
        blank=True,
        help_text="Optional overlay color applied on top of background image.",
    )
    layout_overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text="Manual layout overrides for section elements.",
    )
    is_hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Page section"
        verbose_name_plural = "Page sections"
        ordering = ("order", "id")

    def __str__(self) -> str:
        return f"{self.get_section_type_display()} (#{self.pk})"


def default_home_layout_overrides() -> dict:
    return {"desktop": {}, "mobile": {}}


class HomePageCopy(models.Model):
    """
    Editable static text for the public home page.
    """
    class HeroLogoLayout(models.TextChoices):
        OVERLAY = "overlay", "Logo over photo"
        STACKED = "stacked", "Logo then photo"

    class HeroLogoBackground(models.TextChoices):
        DARK = "dark", "Dark"
        LIGHT = "light", "Light"
        ACCENT = "accent", "Accent"
        TRANSPARENT = "transparent", "Transparent"

    singleton_id = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)

    # Meta
    meta_title = models.CharField(
        max_length=140,
        default="BGM — Performance Builds & VIP Service",
    )
    meta_description = models.TextField(
        default="Performance-driven builds, detailing, tuning, and a curated product catalog by BGM in Calgary.",
    )
    default_background = models.ForeignKey(
        BackgroundAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="home_default_backgrounds",
        help_text="Optional default background for the home page.",
    )

    # Header & navigation
    skip_to_main_label = models.CharField(max_length=120, default="Skip to main content")
    brand_word_white = models.CharField(max_length=40, default="BAD GUY")
    brand_word_red = models.CharField(max_length=40, default="MOTORS")
    brand_tagline = models.CharField(max_length=120, default="CUSTOM BUILDS • INSTALLS • UPGRADES")
    nav_toggle_label = models.CharField(max_length=80, default="Toggle navigation")
    nav_services_label = models.CharField(max_length=40, default="Services")
    nav_client_portal_label = models.CharField(max_length=60, default="Client Portal")
    nav_login_label = models.CharField(max_length=40, default="Login")
    nav_products_label = models.CharField(max_length=40, default="Products")
    nav_merch_label = models.CharField(max_length=40, default="Merch")
    nav_merch_badge = models.CharField(max_length=20, default="Soon")
    nav_dealers_label = models.CharField(max_length=40, default="Dealers")
    nav_financing_label = models.CharField(max_length=40, default="Financing")
    nav_about_label = models.CharField(max_length=40, default="About")

    # Hero
    hero_logo = models.ImageField(
        upload_to="home/branding/",
        blank=True,
        null=True,
        help_text="Optional circular logo shown above the hero copy.",
    )
    hero_logo_backdrop = models.ImageField(
        upload_to="home/branding/",
        blank=True,
        null=True,
        help_text="Optional backdrop photo displayed behind the circular logo.",
    )
    hero_logo_layout = models.CharField(
        max_length=12,
        choices=HeroLogoLayout.choices,
        default=HeroLogoLayout.OVERLAY,
        help_text="Controls whether the logo overlays the photo or the photo appears below it.",
    )
    hero_logo_bg_style = models.CharField(
        max_length=16,
        choices=HeroLogoBackground.choices,
        default=HeroLogoBackground.DARK,
        help_text="Background style for the circular logo container.",
    )
    hero_logo_size = models.PositiveSmallIntegerField(
        default=180,
        validators=[MinValueValidator(96), MaxValueValidator(260)],
        help_text="Logo diameter in pixels (desktop).",
    )
    hero_logo_show_ring = models.BooleanField(
        default=True,
        help_text="Show circular ring around the hero logo.",
    )
    hero_logo_photo_width = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Optional width (px) for the photo under the logo (stacked layout only).",
    )
    hero_logo_photo_height = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Optional height (px) for the photo under the logo (stacked layout only).",
    )
    hero_media_width = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Optional hero image width (desktop px). Leave empty for auto.",
    )
    hero_media_height = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Optional hero image height (desktop px). Leave empty for auto.",
    )
    hero_logo_alt = models.CharField(
        max_length=160,
        default="BGM logo",
        blank=True,
        help_text="Accessible alt text for the hero logo image.",
    )
    hero_kicker = models.CharField(max_length=120, default="Custom fabrication • Diesel performance")
    hero_title = models.CharField(max_length=140, default="Built to be bad. Engineered to last.")
    hero_lead = models.TextField(
        default=(
            "Bad Guy Motors is Medicine Hat’s premier custom fab and diesel shop. "
            "We design and build bumpers, body swaps, lift kits & four-links, and performance upgrades—"
            "then finish them with Armadillo or Smooth Criminal Liner. Book a consult and we’ll map your "
            "build from concept to keys."
        )
    )
    hero_primary_cta_label = models.CharField(max_length=60, default="Explore services")
    hero_secondary_cta_label = models.CharField(max_length=60, default="Booking")
    hero_stat_1_title = models.CharField(max_length=60, default="Alberta-made")
    hero_stat_1_subtitle = models.CharField(max_length=80, default="built in Medicine Hat")
    hero_stat_2_title = models.CharField(max_length=60, default="Custom only")
    hero_stat_2_subtitle = models.CharField(max_length=80, default="no cookie‑cutter kits")
    hero_stat_3_title = models.CharField(max_length=60, default="24/7")
    hero_stat_3_subtitle = models.CharField(max_length=80, default="Book online fast quotes")

    hero_background_asset = models.ForeignKey(
        BackgroundAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="home_pages",
        help_text="Optional background from the library (overrides the uploaded hero background).",
    )

    layout_overrides = models.JSONField(
        default=default_home_layout_overrides,
        blank=True,
        help_text="Manual layout offsets for hero elements (page builder).",
    )

    hero_mobile_action_1_title = models.CharField(max_length=60, default="Book a Service")
    hero_mobile_action_1_subtitle = models.CharField(max_length=80, default="Pick date & time")
    hero_mobile_action_2_title = models.CharField(max_length=60, default="Shop Parts")
    hero_mobile_action_2_subtitle = models.CharField(max_length=80, default="In stock & ready")
    hero_mobile_action_3_title = models.CharField(max_length=60, default="Contact Us")
    hero_mobile_action_3_subtitle = models.CharField(max_length=80, default="Call or e‑mail")
    hero_mobile_action_4_title = models.CharField(max_length=60, default="About")
    hero_mobile_action_4_subtitle = models.CharField(max_length=80, default="Who we are")

    # Services section
    services_title = models.CharField(max_length=80, default="What we build")
    services_desc = models.TextField(
        default=(
            "From bolt‑on to one‑off: bumpers, chase racks, headache racks, mudflaps, running boards, "
            "lift kits & 4‑links, diesel tuning & hard parts, coatings & liners, body swaps, and more. "
            "Browse packages or request a custom quote."
        )
    )
    services_cta_label = models.CharField(max_length=60, default="Open services")
    services_mobile_kicker = models.CharField(max_length=60, default="Quick picks")
    services_mobile_action_1_title = models.CharField(max_length=60, default="Fabrication")
    services_mobile_action_1_subtitle = models.CharField(max_length=80, default="Bumpers, racks, swaps")
    services_mobile_action_2_title = models.CharField(max_length=60, default="Suspension")
    services_mobile_action_2_subtitle = models.CharField(max_length=80, default="Lift kits & 4‑links")
    services_mobile_action_3_title = models.CharField(max_length=60, default="Diesel Tuning")
    services_mobile_action_3_subtitle = models.CharField(max_length=80, default="Turbo, injectors, ECU")
    services_mobile_action_4_title = models.CharField(max_length=60, default="Coatings")
    services_mobile_action_4_subtitle = models.CharField(max_length=80, default="Armadillo & liner")

    services_search_placeholder = models.CharField(max_length=120, default="Search a service…")
    services_filter_all_categories_label = models.CharField(max_length=60, default="All categories")
    services_search_button_label = models.CharField(max_length=40, default="Search")
    services_reset_filters_label = models.CharField(max_length=60, default="Reset filters")
    services_live_results_label = models.CharField(max_length=60, default="Search results")
    services_results_label = models.CharField(max_length=60, default="Results")
    services_featured_label = models.CharField(max_length=80, default="Featured services")
    services_no_results_label = models.CharField(max_length=120, default="No results for your query.")
    services_empty_label = models.CharField(max_length=140, default="The catalog will be available soon 👍")
    services_duration_prefix = models.CharField(max_length=40, default="Duration:")
    services_duration_suffix = models.CharField(max_length=40, default="min")
    services_book_now_label = models.CharField(max_length=40, default="Book now")
    services_nothing_found_label = models.CharField(max_length=80, default="Nothing found.")
    services_failed_load_label = models.CharField(
        max_length=120,
        default="Failed to load. Please try again.",
    )

    # Gallery section
    gallery_title = models.CharField(max_length=80, default="Project gallery")
    gallery_desc = models.TextField(
        default="Recent builds, wraps, and installs from the BGM shop floor.",
    )
    gallery_cta_label = models.CharField(max_length=60, default="View photo gallery")
    gallery_cta_url = models.CharField(max_length=200, default="/project-journal/", blank=True)

    contact_for_estimate_label = models.CharField(max_length=80, default="Contact for estimate")
    from_label = models.CharField(max_length=40, default="From")

    # Products section
    products_title = models.CharField(max_length=80, default="Products")
    products_desc = models.CharField(
        max_length=160,
        default="Performance parts curated by BGM. Fresh stock, ready to ship.",
    )
    products_cta_label = models.CharField(max_length=60, default="Open products")
    products_mobile_kicker = models.CharField(max_length=60, default="Quick shop")
    products_mobile_action_1_title = models.CharField(max_length=60, default="Shop Parts")
    products_mobile_action_1_subtitle = models.CharField(max_length=80, default="Fresh stock")
    products_mobile_action_2_title = models.CharField(max_length=60, default="Merch")
    products_mobile_action_2_subtitle = models.CharField(max_length=80, default="Coming soon")
    products_dealer_label = models.CharField(max_length=40, default="Dealer")
    products_save_label = models.CharField(max_length=40, default="Save")
    products_contact_us_label = models.CharField(max_length=40, default="Contact us")
    products_view_label = models.CharField(max_length=40, default="View")
    products_select_options_label = models.CharField(max_length=60, default="Select options")
    products_add_to_cart_label = models.CharField(max_length=40, default="Add to cart")
    products_empty_label = models.CharField(max_length=80, default="No products yet.")
    products_empty_cta_label = models.CharField(max_length=80, default="Explore products")

    # How it works
    how_title = models.CharField(max_length=80, default="How we work")
    how_desc = models.CharField(max_length=120, default="A transparent cycle—from booking to delivery.")
    how_step_1_title = models.CharField(max_length=80, default="Consult & scope")
    how_step_1_desc = models.CharField(max_length=120, default="Tell us your goals, budget, and timeline.")
    how_step_2_title = models.CharField(max_length=80, default="Design & quote")
    how_step_2_desc = models.CharField(
        max_length=140,
        default="CAD as needed, milestones, and a written estimate.",
    )
    how_step_3_title = models.CharField(max_length=80, default="Fabricate & update")
    how_step_3_desc = models.CharField(
        max_length=140,
        default="Progress pics, approvals, and clear communication.",
    )
    how_step_4_title = models.CharField(max_length=80, default="Delivery & aftercare")
    how_step_4_desc = models.CharField(
        max_length=140,
        default="Test drive, torque check, and a care guide.",
    )

    # Why BGM
    why_title = models.CharField(max_length=80, default="Why choose BGM")
    why_desc = models.CharField(
        max_length=140,
        default="We combine aesthetics with engineering discipline.",
    )
    why_tile_1_title = models.CharField(max_length=80, default="No‑compromise materials")
    why_tile_1_desc = models.CharField(max_length=120, default="DOM tubing, proper hardware, and proven parts.")
    why_tile_2_title = models.CharField(max_length=80, default="On‑time, transparent")
    why_tile_2_desc = models.CharField(max_length=120, default="Clear updates, zero guesswork.")
    why_tile_3_title = models.CharField(max_length=80, default="Built for abuse")
    why_tile_3_desc = models.CharField(
        max_length=120,
        default="Designed to work hard, not just look pretty.",
    )
    why_warranty_title = models.CharField(max_length=80, default="Warranty & support")
    why_warranty_desc = models.CharField(
        max_length=120,
        default="We stand behind our work and make things right.",
    )
    why_warranty_cta = models.CharField(max_length=80, default="Read terms →")
    why_warranty_aria_label = models.CharField(max_length=120, default="Read Terms & Conditions")
    why_warranty_title_attr = models.CharField(max_length=120, default="Warranty & support details")

    # FAQ
    faq_title = models.CharField(max_length=40, default="FAQ")
    faq_desc = models.CharField(max_length=80, default="Short and sweet")
    faq_1_question = models.CharField(max_length=160, default="Do I need a prepayment?")
    faq_1_answer = models.CharField(
        max_length=220,
        default="For some services — yes (the “prepayment” option in the service card). Others — pay upon completion.",
    )
    faq_2_question = models.CharField(max_length=160, default="Can I reschedule?")
    faq_2_answer = models.CharField(
        max_length=220,
        default="Yes. In the client portal you can cancel or reschedule, and we’ll auto-suggest free slots.",
    )
    faq_3_question = models.CharField(max_length=160, default="Do you work with companies and dealers?")
    faq_3_answer = models.CharField(
        max_length=220,
        default="Yes. The “Dealers” section is coming soon. Leave a request via the contact form.",
    )

    # Final CTA
    final_cta_title = models.CharField(max_length=80, default="Ready to upgrade?")
    final_cta_desc = models.CharField(
        max_length=120,
        default="We’ll secure your slot and lock the terms today.",
    )
    final_cta_primary_label = models.CharField(max_length=60, default="Explore services")
    final_cta_secondary_auth_label = models.CharField(max_length=60, default="Client Portal")
    final_cta_secondary_guest_label = models.CharField(max_length=60, default="Login")

    # Contact modal
    contact_fab_label = models.CharField(max_length=60, default="Contact us")
    contact_modal_title = models.CharField(max_length=60, default="Contact us")
    contact_email_label = models.CharField(max_length=40, default="E-mail")
    contact_phone_label = models.CharField(max_length=40, default="Phone")
    contact_copy_label = models.CharField(max_length=40, default="Copy")
    contact_copy_success_label = models.CharField(max_length=40, default="Copied")
    contact_copy_failed_label = models.CharField(max_length=40, default="Copy failed")
    contact_call_label = models.CharField(max_length=40, default="Call")
    contact_write_email_label = models.CharField(max_length=60, default="Write e-mail")
    contact_text_label = models.CharField(max_length=40, default="Text us")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Home page copy"
        verbose_name_plural = "Home page copy"
        ordering = ("singleton_id",)

    def __str__(self) -> str:
        return "Home page copy"

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_id=1)
        return obj


class ServicesPageCopy(models.Model):
    """
    Editable static text for the services catalog page.
    """
    singleton_id = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)

    meta_title = models.CharField(max_length=160, default="Bad Guy Motors — Upgrades & Booking")
    meta_description = models.TextField(
        default="Browse detailing, protection, and performance services with live pricing from Bad Guy Motors."
    )
    default_background = models.ForeignKey(
        BackgroundAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="services_default_backgrounds",
        help_text="Optional default background for the services page.",
    )

    skip_to_main_label = models.CharField(max_length=120, default="Skip to main content")
    brand_word_white = models.CharField(max_length=40, default="BAD GUY")
    brand_word_red = models.CharField(max_length=40, default="MOTORS")
    brand_tagline = models.CharField(max_length=120, default="CUSTOM BUILDS • INSTALLS • UPGRADES")
    nav_toggle_label = models.CharField(max_length=80, default="Toggle navigation")
    nav_services_label = models.CharField(max_length=40, default="Services")
    nav_client_portal_label = models.CharField(max_length=60, default="Client Portal")
    nav_login_label = models.CharField(max_length=40, default="Login")
    nav_products_label = models.CharField(max_length=40, default="Products")
    nav_merch_label = models.CharField(max_length=40, default="Merch")
    nav_merch_badge = models.CharField(max_length=20, default="Soon")
    nav_dealers_label = models.CharField(max_length=40, default="Dealers")
    nav_financing_label = models.CharField(max_length=40, default="Financing")
    nav_about_label = models.CharField(max_length=40, default="About")

    hero_title = models.CharField(max_length=140, default="Built to be bad. Engineered to last.")
    hero_lead = models.TextField(
        default=(
            "Book custom fabrication, diesel performance, coatings, body swaps and more — "
            "bumpers, headache & chase racks, mudflaps, running boards, fender flares, "
            "lift kits & 4‑links, tuning, and installs."
        )
    )
    hero_cta_label = models.CharField(max_length=80, default="Browse services ↓")

    section_title = models.CharField(max_length=80, default="Upgrades & Services")
    search_placeholder = models.CharField(max_length=120, default="Search a service…")
    filter_all_categories_label = models.CharField(max_length=60, default="All categories")
    search_button_label = models.CharField(max_length=40, default="Search")
    reset_button_label = models.CharField(max_length=40, default="Reset")
    search_results_label = models.CharField(max_length=60, default="Search results")
    live_no_results_label = models.CharField(max_length=80, default="No services found.")
    live_error_label = models.CharField(max_length=120, default="Could not load results. Please try again.")
    search_no_results_prefix = models.CharField(max_length=80, default="No results for")
    search_no_results_suffix = models.CharField(max_length=40, default=".")
    category_empty_label = models.CharField(max_length=120, default="No services in this category yet.")
    uncategorized_title = models.CharField(max_length=80, default="Uncategorized")
    catalog_empty_label = models.CharField(max_length=140, default="The catalog will be available soon 👍")

    service_image_aria_label = models.CharField(max_length=80, default="Service image")
    service_image_fallback_label = models.CharField(max_length=40, default="BGM • SERVICE")
    book_aria_prefix = models.CharField(max_length=40, default="Book")
    pick_time_label = models.CharField(max_length=60, default="Pick a time")
    contact_for_estimate_label = models.CharField(max_length=80, default="Contact for estimate")
    from_label = models.CharField(max_length=40, default="From")
    duration_separator = models.CharField(max_length=8, default="·")
    duration_unit = models.CharField(max_length=20, default="min")

    booking_modal_title_prefix = models.CharField(max_length=80, default="Booking for")
    booking_close_label = models.CharField(max_length=40, default="Close")
    booking_staff_label = models.CharField(max_length=40, default="Staff")
    booking_staff_picker_label = models.CharField(max_length=80, default="Pick a staff member")
    booking_choose_time_label = models.CharField(max_length=60, default="Choose time")
    booking_prev_label = models.CharField(max_length=20, default="← Prev")
    booking_today_label = models.CharField(max_length=20, default="Today")
    booking_next_label = models.CharField(max_length=20, default="Next →")
    booking_mobile_day_label = models.CharField(max_length=20, default="Day")
    booking_mobile_pick_day_label = models.CharField(max_length=60, default="Pick a day")
    booking_jump_today_label = models.CharField(max_length=60, default="Jump to today")
    booking_available_times_label = models.CharField(max_length=60, default="Available times")
    booking_no_open_times_label = models.CharField(max_length=120, default="No open times for this day.")
    booking_no_open_times_on_prefix = models.CharField(max_length=80, default="No open times on")
    booking_no_open_times_on_suffix = models.CharField(max_length=20, default=".")
    booking_no_availability_label = models.CharField(max_length=80, default="No availability yet")
    booking_scroll_hint_desktop = models.CharField(
        max_length=200,
        default="Shift + scroll for horizontal scroll. Red = busy (unclickable).",
    )
    booking_scroll_hint_mobile = models.CharField(
        max_length=200,
        default="Swipe left/right to see more days. Red = busy (unclickable).",
    )
    booking_summary_label = models.CharField(max_length=40, default="Summary")
    booking_summary_default = models.CharField(max_length=120, default="Pick a staff member and time.")
    booking_summary_staff_prefix = models.CharField(max_length=40, default="Staff:")
    booking_summary_time_prefix = models.CharField(max_length=40, default="Time:")
    booking_summary_time_selected_label = models.CharField(max_length=80, default="Time selected.")
    booking_full_name_label = models.CharField(max_length=60, default="Full name*")
    booking_full_name_placeholder = models.CharField(max_length=120, default="John Doe")
    booking_email_label = models.CharField(max_length=40, default="Email*")
    booking_email_placeholder = models.CharField(max_length=120, default="you@example.com")
    booking_phone_label = models.CharField(max_length=40, default="Phone*")
    booking_phone_placeholder = models.CharField(max_length=120, default="+1 5551234567")
    booking_phone_title = models.CharField(max_length=120, default="Use digits only, optionally starting with +")
    booking_confirmation_hint = models.CharField(
        max_length=160,
        default="No account needed — we confirm bookings by email and phone.",
    )
    booking_cancel_label = models.CharField(max_length=40, default="Cancel")
    booking_confirm_label = models.CharField(max_length=60, default="Confirm booking")
    booking_no_staff_label = models.CharField(max_length=80, default="No staff available")
    booking_availability_error_label = models.CharField(max_length=120, default="Unable to fetch availability")
    booking_failed_slots_label = models.CharField(max_length=120, default="Failed to load available slots")
    booking_missing_contact_error = models.CharField(
        max_length=120,
        default="Please add your name, email and phone.",
    )
    booking_create_error_label = models.CharField(max_length=120, default="Could not create an appointment")
    booking_created_label = models.CharField(max_length=80, default="Appointment created!")
    booking_time_label = models.CharField(max_length=40, default="Time:")
    booking_error_label = models.CharField(max_length=80, default="Booking error")

    contact_fab_label = models.CharField(max_length=60, default="Contact us")
    contact_modal_title = models.CharField(max_length=60, default="Contact us")
    contact_close_label = models.CharField(max_length=40, default="Close")
    contact_email_label = models.CharField(max_length=40, default="E-mail")
    contact_phone_label = models.CharField(max_length=40, default="Phone")
    contact_copy_label = models.CharField(max_length=40, default="Copy")
    contact_copy_success_label = models.CharField(max_length=40, default="Copied")
    contact_copy_failed_label = models.CharField(max_length=40, default="Copy failed")
    contact_call_label = models.CharField(max_length=40, default="Call")
    contact_write_email_label = models.CharField(max_length=60, default="Write e-mail")
    contact_text_label = models.CharField(max_length=40, default="Text us")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Services page copy"
        verbose_name_plural = "Services page copy"
        ordering = ("singleton_id",)

    def __str__(self) -> str:
        return "Services page copy"

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_id=1)
        return obj


class StorePageCopy(models.Model):
    """
    Editable static text for the store (products) page.
    """
    singleton_id = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)

    page_title = models.CharField(max_length=160, default="BGM — Products")
    meta_title = models.CharField(max_length=160, default="BGM Customs — Storefront")
    meta_description = models.TextField(
        default="Shop curated parts, aero, lighting, and performance upgrades from BGM Customs."
    )
    default_background = models.ForeignKey(
        BackgroundAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="store_default_backgrounds",
        help_text="Optional default background for the store page.",
    )

    brand_word_white = models.CharField(max_length=40, default="BAD GUY")
    brand_word_red = models.CharField(max_length=40, default="MOTORS")
    brand_tagline = models.CharField(max_length=120, default="CUSTOM BUILDS • INSTALLS • UPGRADES")
    nav_toggle_label = models.CharField(max_length=80, default="Toggle navigation")
    nav_services_label = models.CharField(max_length=40, default="Services")
    nav_client_portal_label = models.CharField(max_length=60, default="Client Portal")
    nav_login_label = models.CharField(max_length=40, default="Login")
    nav_products_label = models.CharField(max_length=40, default="Products")
    nav_merch_label = models.CharField(max_length=40, default="Merch")
    nav_merch_badge = models.CharField(max_length=20, default="Soon")
    nav_dealers_label = models.CharField(max_length=40, default="Dealers")
    nav_financing_label = models.CharField(max_length=40, default="Financing")
    nav_about_label = models.CharField(max_length=40, default="About")

    hero_title = models.CharField(max_length=80, default="Parts & Upgrades")
    hero_lead = models.CharField(max_length=160, default="Performance parts curated by BGM.")
    hero_primary_cta_label = models.CharField(max_length=60, default="Book install")
    hero_secondary_cta_label = models.CharField(max_length=60, default="Open cart")
    hero_disclaimer_fallback = models.CharField(
        max_length=140,
        default="Product may not appear exactly as shown.",
    )

    filters_toggle_label = models.CharField(max_length=40, default="Filters")
    filters_active_badge = models.CharField(max_length=20, default="Active")
    filters_reset_label = models.CharField(max_length=40, default="Reset")
    filters_heading = models.CharField(max_length=40, default="Filters")
    filters_close_label = models.CharField(max_length=40, default="Close")
    filters_category_label = models.CharField(max_length=40, default="Category")
    filters_make_label = models.CharField(max_length=40, default="Make")
    filters_model_label = models.CharField(max_length=40, default="Model")
    filters_year_label = models.CharField(max_length=40, default="Year")
    filters_apply_label = models.CharField(max_length=60, default="Apply filters")
    filters_clear_label = models.CharField(max_length=40, default="Clear")

    categories_title = models.CharField(max_length=60, default="Categories")
    categories_desc = models.CharField(max_length=80, default="Pick a category to explore")
    categories_empty_label = models.CharField(max_length=80, default="No categories yet.")

    results_title = models.CharField(max_length=60, default="Results")
    results_desc = models.CharField(max_length=80, default="Filtered products")
    results_empty_label = models.CharField(max_length=80, default="No products found.")

    new_arrivals_title = models.CharField(max_length=60, default="New arrivals")
    new_arrivals_cart_label = models.CharField(max_length=40, default="Cart")

    browse_title = models.CharField(max_length=80, default="Browse by category")
    browse_desc = models.CharField(max_length=80, default="Explore all categories")
    browse_view_all_label = models.CharField(max_length=40, default="View all")

    comparison_title = models.CharField(max_length=80, default="Armadillo vs SCL")
    comparison_desc = models.CharField(
        max_length=160,
        default="Two liner finishes, two personalities. Compare the feel before you book.",
    )
    comparison_left_title = models.CharField(max_length=60, default="Armadillo")
    comparison_left_subtitle = models.CharField(max_length=80, default="Textured, rugged liner")
    comparison_left_body = models.TextField(
        default="Thick, textured finish built for abuse.\nIdeal for heavy-use beds and work rigs.\nMaximum grip and impact resistance.",
    )
    comparison_right_title = models.CharField(max_length=60, default="SCL")
    comparison_right_subtitle = models.CharField(max_length=80, default="Smooth Criminal Liner")
    comparison_right_body = models.TextField(
        default="Smoother finish with a show-ready look.\nEasy to clean with a sleek feel.\nGreat for street builds and interiors.",
    )

    contact_for_estimate_label = models.CharField(max_length=80, default="Contact for estimate")
    from_label = models.CharField(max_length=40, default="From")
    dealer_label = models.CharField(max_length=40, default="Dealer")
    save_label = models.CharField(max_length=40, default="Save")

    contact_fab_label = models.CharField(max_length=60, default="Contact us")
    contact_modal_title = models.CharField(max_length=60, default="Contact us")
    contact_close_label = models.CharField(max_length=40, default="Close")
    contact_email_label = models.CharField(max_length=40, default="E-mail")
    contact_phone_label = models.CharField(max_length=40, default="Phone")
    contact_copy_label = models.CharField(max_length=40, default="Copy")
    contact_copy_success_label = models.CharField(max_length=40, default="Copied")
    contact_copy_failed_label = models.CharField(max_length=40, default="Copy failed")
    contact_call_label = models.CharField(max_length=40, default="Call")
    contact_write_email_label = models.CharField(max_length=60, default="Write e-mail")
    contact_text_label = models.CharField(max_length=40, default="Text us")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Store page copy"
        verbose_name_plural = "Store page copy"
        ordering = ("singleton_id",)

    def __str__(self) -> str:
        return "Store page copy"

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_id=1)
        return obj


class ClientPortalPageCopy(models.Model):
    """
    Editable static text for the client portal (dashboard) page.
    """
    singleton_id = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)

    page_title = models.CharField(max_length=160, default="Bad Guy Motors | Client Portal")
    meta_title = models.CharField(max_length=160, default="Bad Guy Motors | Client Portal")
    meta_description = models.TextField(
        default="Manage appointments, check project status, and review invoices in the client portal."
    )

    brand_mark = models.CharField(max_length=20, default="BGM")
    brand_name = models.CharField(max_length=80, default="Client Portal")
    mobile_menu_label = models.CharField(max_length=40, default="Menu")
    mobile_controls_aria_label = models.CharField(max_length=80, default="Portal controls")
    sidebar_close_label = models.CharField(max_length=40, default="Close menu")

    nav_overview_label = models.CharField(max_length=40, default="Overview")
    nav_appointments_label = models.CharField(max_length=60, default="Appointments")
    nav_orders_label = models.CharField(max_length=40, default="Orders")
    nav_files_label = models.CharField(max_length=40, default="Files")
    nav_notifications_label = models.CharField(max_length=60, default="Notifications")
    nav_profile_label = models.CharField(max_length=40, default="Profile")
    nav_back_home_label = models.CharField(max_length=60, default="Back to Home")
    nav_sign_out_label = models.CharField(max_length=40, default="Sign out")

    welcome_back_prefix = models.CharField(max_length=80, default="Welcome back,")
    welcome_back_suffix = models.CharField(max_length=20, default=".")
    dashboard_kicker = models.CharField(
        max_length=200,
        default="Keep your builds on schedule. No mercy for missed slots.",
    )

    upcoming_title = models.CharField(max_length=40, default="Upcoming")
    upcoming_empty_label = models.CharField(max_length=120, default="No upcoming appointments.")
    action_cancel_label = models.CharField(max_length=40, default="Cancel")
    action_reschedule_label = models.CharField(max_length=60, default="Reschedule")
    stats_title = models.CharField(max_length=40, default="Stats")
    stats_chart_label = models.CharField(max_length=60, default="Appointments")
    recent_title = models.CharField(max_length=80, default="Recent appointments")
    recent_empty_label = models.CharField(max_length=120, default="No completed appointments yet.")
    table_date_label = models.CharField(max_length=40, default="Date")
    table_service_label = models.CharField(max_length=40, default="Service")
    table_staff_label = models.CharField(max_length=40, default="Staff")
    table_status_label = models.CharField(max_length=40, default="Status")
    table_amount_label = models.CharField(max_length=40, default="Amount")

    rates_title = models.CharField(max_length=40, default="Rates")
    rates_shop_label = models.CharField(max_length=40, default="Shop rate")
    rates_shop_value = models.CharField(max_length=40, default="130/hr")
    rates_cad_label = models.CharField(max_length=60, default="Design/CAD rate")
    rates_cad_value = models.CharField(max_length=40, default="150/hr")
    quick_facts_title = models.CharField(max_length=60, default="Quick facts")
    quick_fact_1 = models.CharField(max_length=160, default="Alberta-made parts, built in Medicine Hat")
    quick_fact_2 = models.CharField(max_length=160, default="Custom fabrication, diesel performance, coatings")
    quick_fact_3 = models.CharField(max_length=160, default="Warranty & aftercare included with every build")

    policies_title = models.CharField(max_length=80, default="Shop info & policies")
    policy_item_1 = models.CharField(max_length=200, default="Deposits secure your slot; balances due on delivery.")
    policy_item_2 = models.CharField(
        max_length=200,
        default="Storage fees may apply for completed items not picked up in a timely manner.",
    )
    policy_item_3 = models.CharField(max_length=200, default="We use DOM tubing, quality hardware, and proven components.")
    policy_item_4 = models.CharField(
        max_length=200,
        default="Transparent timelines with progress updates in your portal.",
    )
    care_title = models.CharField(max_length=80, default="Care & warranty")
    care_item_1 = models.CharField(
        max_length=200,
        default="Torque checks after install; follow-up available by appointment.",
    )
    care_item_2 = models.CharField(
        max_length=240,
        default="Coatings (Armadillo / Smooth Criminal Liner): mild soap, soft brush; avoid harsh solvents.",
    )
    care_item_3 = models.CharField(
        max_length=200,
        default="We stand behind our work—if something isn’t right, tell us and we’ll make it right.",
    )

    appointments_title = models.CharField(max_length=60, default="My appointments")
    appointments_book_label = models.CharField(max_length=40, default="+ Book")
    appointments_completed_label = models.CharField(max_length=40, default="Completed")
    appointments_empty_label = models.CharField(max_length=80, default="No appointments.")

    orders_title = models.CharField(max_length=60, default="My orders")
    orders_go_to_products_label = models.CharField(max_length=60, default="Go to products")
    orders_empty_label = models.CharField(max_length=80, default="No orders yet.")

    files_title = models.CharField(max_length=60, default="Files")
    files_lead = models.CharField(
        max_length=200,
        default="Upload insurance papers, IDs, or inspiration photos for our team.",
    )
    files_max_size_label = models.CharField(max_length=40, default="Max size:")
    files_description_label = models.CharField(max_length=60, default="Description (optional)")
    files_description_placeholder = models.CharField(max_length=120, default="e.g. Insurance approval")
    files_dropzone_title = models.CharField(max_length=120, default="Drop a file here or click to browse")
    files_accepted_prefix = models.CharField(
        max_length=180,
        default="Accepted: images (JPG, PNG, WEBP, HEIC) or PDF. Max ",
    )
    files_accepted_suffix = models.CharField(max_length=40, default=" MB.")
    files_choose_label = models.CharField(max_length=40, default="Choose file")
    files_your_files_title = models.CharField(max_length=60, default="Your files")
    files_total_suffix = models.CharField(max_length=20, default="total")
    files_empty_label = models.CharField(
        max_length=160,
        default="No files yet. Upload your first document or photo.",
    )
    files_remove_label = models.CharField(max_length=40, default="Remove")
    files_file_fallback_label = models.CharField(max_length=40, default="File")

    notifications_title = models.CharField(max_length=60, default="Notifications")
    notifications_empty_label = models.CharField(max_length=80, default="Coming soon.")

    profile_title = models.CharField(max_length=60, default="Profile")
    profile_first_name_label = models.CharField(max_length=40, default="First name")
    profile_last_name_label = models.CharField(max_length=40, default="Last name")
    profile_phone_label = models.CharField(max_length=40, default="Phone")
    profile_email_label = models.CharField(max_length=40, default="E-mail")
    profile_birth_date_label = models.CharField(max_length=40, default="Birth date")
    profile_save_label = models.CharField(max_length=60, default="Save changes")
    profile_email_prefs_title = models.CharField(max_length=80, default="Email preferences")
    profile_email_marketing_label = models.CharField(max_length=120, default="News & offers")
    profile_email_product_label = models.CharField(max_length=120, default="Product drops & merch alerts")
    profile_email_service_label = models.CharField(max_length=120, default="Build updates & service reminders")

    reschedule_modal_title = models.CharField(max_length=80, default="Reschedule appointment")
    reschedule_close_label = models.CharField(max_length=40, default="Close")
    reschedule_staff_label = models.CharField(max_length=40, default="Staff")
    reschedule_choose_time_label = models.CharField(max_length=60, default="Choose time")
    reschedule_prev_label = models.CharField(max_length=20, default="← Prev")
    reschedule_today_label = models.CharField(max_length=20, default="Today")
    reschedule_next_label = models.CharField(max_length=20, default="Next →")
    reschedule_shift_scroll_hint = models.CharField(
        max_length=160,
        default="Shift+Scroll gives horizontal scrolling. Gray slots are already booked.",
    )
    reschedule_cancel_label = models.CharField(max_length=40, default="Cancel")
    reschedule_save_label = models.CharField(max_length=40, default="Save")
    reschedule_no_techs_label = models.CharField(max_length=80, default="No techs available")
    reschedule_no_availability_label = models.CharField(max_length=80, default="No availability")
    reschedule_fetch_error_label = models.CharField(max_length=120, default="Unable to fetch availability")
    reschedule_failed_slots_label = models.CharField(max_length=120, default="Failed to load slots")
    reschedule_success_prefix = models.CharField(max_length=80, default="Rescheduled to ")
    reschedule_failed_label = models.CharField(max_length=80, default="Reschedule failed")

    cancel_confirm_message = models.CharField(max_length=120, default="Cancel this appointment?")
    cancel_error_prefix = models.CharField(max_length=80, default="Cancel error: ")

    files_removing_label = models.CharField(max_length=60, default="Removing…")
    files_removed_label = models.CharField(max_length=80, default="File removed.")
    files_delete_failed_label = models.CharField(max_length=80, default="Delete failed.")
    files_delete_error_label = models.CharField(max_length=120, default="Unable to delete file.")
    files_uploading_label = models.CharField(max_length=60, default="Uploading…")
    files_upload_success_label = models.CharField(max_length=80, default="Uploaded successfully.")
    files_upload_failed_label = models.CharField(max_length=80, default="Upload failed.")
    files_too_large_prefix = models.CharField(max_length=80, default="File exceeds ")
    files_too_large_suffix = models.CharField(max_length=40, default=" MB limit.")

    contact_fab_label = models.CharField(max_length=60, default="Contact us")
    contact_modal_title = models.CharField(max_length=60, default="Contact us")
    contact_close_label = models.CharField(max_length=40, default="Close")
    contact_email_label = models.CharField(max_length=40, default="E-mail")
    contact_phone_label = models.CharField(max_length=40, default="Phone")
    contact_copy_label = models.CharField(max_length=40, default="Copy")
    contact_copy_success_label = models.CharField(max_length=40, default="Copied")
    contact_copy_failed_label = models.CharField(max_length=40, default="Copy failed")
    contact_call_label = models.CharField(max_length=40, default="Call")
    contact_write_email_label = models.CharField(max_length=60, default="Write e-mail")
    contact_text_label = models.CharField(max_length=40, default="Text us")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Client portal copy"
        verbose_name_plural = "Client portal copy"
        ordering = ("singleton_id",)

    def __str__(self) -> str:
        return "Client portal copy"

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_id=1)
        return obj


class MerchPageCopy(models.Model):
    """
    Editable static text for the merch page.
    """
    singleton_id = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)

    page_title = models.CharField(max_length=160, default="BGM Customs — Merch (Coming Soon)")
    meta_title = models.CharField(max_length=160, default="BGM Customs — Merch (Coming Soon)")
    meta_description = models.TextField(
        default="Streetwear, track gear, and pit essentials from BGM Customs are on the way. Join the drop list."
    )

    skip_to_main_label = models.CharField(max_length=120, default="Skip to main content")
    brand_word_white = models.CharField(max_length=40, default="BAD GUY")
    brand_word_red = models.CharField(max_length=40, default="MOTORS")
    brand_tagline = models.CharField(max_length=120, default="CUSTOM BUILDS • INSTALLS • UPGRADES")
    nav_toggle_label = models.CharField(max_length=80, default="Toggle navigation")
    nav_services_label = models.CharField(max_length=40, default="Services")
    nav_client_portal_label = models.CharField(max_length=60, default="Client Portal")
    nav_login_label = models.CharField(max_length=40, default="Login")
    nav_products_label = models.CharField(max_length=40, default="Products")
    nav_merch_label = models.CharField(max_length=40, default="Merch")
    nav_merch_badge = models.CharField(max_length=20, default="Soon")
    nav_dealers_label = models.CharField(max_length=40, default="Dealers")
    nav_financing_label = models.CharField(max_length=40, default="Financing")
    nav_about_label = models.CharField(max_length=40, default="About")

    hero_kicker = models.CharField(max_length=60, default="BGM Merch")
    hero_title = models.CharField(max_length=140, default="Apparel & accessories — Coming soon")
    hero_lead = models.TextField(
        default=(
            "Tees, hoodies, caps, wall art — built with the same no-compromise mindset. "
            "Want first drop access? Stay tuned."
        )
    )
    hero_primary_cta_label = models.CharField(max_length=60, default="← Back to Home")
    hero_secondary_cta_label = models.CharField(max_length=60, default="Explore Services")
    hero_disclaimer_fallback = models.CharField(
        max_length=140,
        default="Product may not appear exactly as shown.",
    )

    section_title = models.CharField(max_length=80, default="First drop ideas")
    section_desc = models.CharField(max_length=120, default="We’re sampling cuts, fabrics and prints.")
    section_badge_label = models.CharField(max_length=20, default="WIP")
    coming_soon_enabled = models.BooleanField(default=True)
    coming_soon_badge = models.CharField(max_length=40, default="Coming soon")
    coming_soon_title = models.CharField(max_length=120, default="Merch drop incoming")
    coming_soon_desc = models.CharField(
        max_length=200,
        default="We’re finalizing samples, colours, and sizing. Join the drop list for first access.",
    )

    card_colors_label = models.CharField(max_length=40, default="Colours")
    card_sizes_label = models.CharField(max_length=40, default="Sizes")

    card_1_title = models.CharField(max_length=60, default="T-Shirts")
    card_1_desc = models.CharField(max_length=120, default="Heavyweight cotton, oversized fit.")
    card_1_photo = models.ImageField(upload_to="merch/cards/", blank=True, null=True)
    card_1_photo_alt = models.CharField(max_length=140, blank=True)
    card_1_colors = models.CharField(max_length=160, blank=True)
    card_1_sizes = models.CharField(max_length=160, blank=True)
    card_2_title = models.CharField(max_length=60, default="Hoodies")
    card_2_desc = models.CharField(max_length=120, default="Brushed fleece, embroidered logos.")
    card_2_photo = models.ImageField(upload_to="merch/cards/", blank=True, null=True)
    card_2_photo_alt = models.CharField(max_length=140, blank=True)
    card_2_colors = models.CharField(max_length=160, blank=True)
    card_2_sizes = models.CharField(max_length=160, blank=True)
    card_3_title = models.CharField(max_length=60, default="Caps")
    card_3_desc = models.CharField(max_length=120, default="Low-profile, structured.")
    card_3_photo = models.ImageField(upload_to="merch/cards/", blank=True, null=True)
    card_3_photo_alt = models.CharField(max_length=140, blank=True)
    card_3_colors = models.CharField(max_length=160, blank=True)
    card_3_sizes = models.CharField(max_length=160, blank=True)
    card_4_title = models.CharField(max_length=60, default="Posters")
    card_4_desc = models.CharField(max_length=120, default="Garage & office wall essentials.")
    card_4_photo = models.ImageField(upload_to="merch/cards/", blank=True, null=True)
    card_4_photo_alt = models.CharField(max_length=140, blank=True)
    card_4_colors = models.CharField(max_length=160, blank=True)
    card_4_sizes = models.CharField(max_length=160, blank=True)

    social_section_title = models.CharField(max_length=80, default="Follow the drop")
    social_section_desc = models.CharField(
        max_length=160,
        default="Behind-the-scenes, restocks, and first access alerts.",
    )
    social_link_1_label = models.CharField(max_length=40, default="Instagram")
    social_link_1_url = models.URLField(
        blank=True,
        default="https://www.instagram.com/badguymotors?igsh=N2QwZnVybTJrZW8=",
    )
    social_link_2_label = models.CharField(max_length=40, default="Facebook")
    social_link_2_url = models.URLField(
        blank=True,
        default="https://www.facebook.com/share/1Gsej2u5X4/?mibextid=wwXIfr",
    )
    social_link_3_label = models.CharField(max_length=40, default="YouTube")
    social_link_3_url = models.URLField(
        blank=True,
        default="https://youtube.com/@badguymotors?si=PObKEe6vNMEr3Z2b",
    )
    social_link_4_label = models.CharField(max_length=40, default="TikTok")
    social_link_4_url = models.URLField(
        blank=True,
        default="https://www.tiktok.com/@savoies0?_r=1&_t=ZS-93JwAHrfF5k",
    )

    bottom_cta_label = models.CharField(max_length=40, default="← Home")

    contact_email = models.EmailField(default="support@badguymotors.com")
    contact_email_subject = models.CharField(max_length=120, default="Inquiry from website")
    contact_phone = models.CharField(max_length=32, default="+14035250432")
    contact_phone_display = models.CharField(max_length=40, default="(403) 525-0432")
    contact_fab_label = models.CharField(max_length=60, default="Contact us")
    contact_modal_title = models.CharField(max_length=60, default="Contact us")
    contact_close_label = models.CharField(max_length=40, default="Close")
    contact_email_label = models.CharField(max_length=40, default="E-mail")
    contact_phone_label = models.CharField(max_length=40, default="Phone")
    contact_copy_label = models.CharField(max_length=40, default="Copy")
    contact_copy_success_label = models.CharField(max_length=40, default="Copied")
    contact_copy_failed_label = models.CharField(max_length=40, default="Copy failed")
    contact_call_label = models.CharField(max_length=40, default="Call")
    contact_write_email_label = models.CharField(max_length=60, default="Write e-mail")
    contact_text_label = models.CharField(max_length=40, default="Text us")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Merch page copy"
        verbose_name_plural = "Merch page copy"
        ordering = ("singleton_id",)

    def __str__(self) -> str:
        return "Merch page copy"

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_id=1)
        return obj


class FinancingPageCopy(models.Model):
    """
    Editable static text for the financing page.
    """
    singleton_id = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)

    meta_title = models.CharField(max_length=160, default="BGM Customs — Financing Options")
    meta_description = models.TextField(
        default="Flexible financing partners for builds, parts, and installs including Canadian Financial and Afterpay."
    )

    skip_to_main_label = models.CharField(max_length=120, default="Skip to main content")

    brand_word_white = models.CharField(max_length=40, default="BAD GUY")
    brand_word_red = models.CharField(max_length=40, default="MOTORS")
    brand_tagline = models.CharField(max_length=120, default="CUSTOM BUILDS • INSTALLS • UPGRADES")
    nav_toggle_label = models.CharField(max_length=80, default="Toggle navigation")
    nav_services_label = models.CharField(max_length=40, default="Services")
    nav_client_portal_label = models.CharField(max_length=60, default="Client Portal")
    nav_login_label = models.CharField(max_length=40, default="Login")
    nav_products_label = models.CharField(max_length=40, default="Products")
    nav_merch_label = models.CharField(max_length=40, default="Merch")
    nav_merch_badge = models.CharField(max_length=20, default="Soon")
    nav_dealers_label = models.CharField(max_length=40, default="Dealers")
    nav_financing_label = models.CharField(max_length=40, default="Financing")
    nav_about_label = models.CharField(max_length=40, default="About")

    hero_kicker = models.CharField(max_length=80, default="Flexible Financing")
    hero_title = models.CharField(max_length=120, default="Build now. Pay over time.")
    hero_lead = models.TextField(
        default=(
            "We offer simple financing options for parts, installs, and full custom builds. "
            "Apply in minutes with no impact to your credit score for pre-qualification where available."
        )
    )
    hero_primary_cta_label = models.CharField(max_length=60, default="See options")
    hero_secondary_cta_label = models.CharField(max_length=80, default="Explore Services")
    hero_image_alt = models.CharField(max_length=80, default="Financing hero")
    hero_disclaimer = models.CharField(
        max_length=140,
        default="Product may not appear exactly as shown.",
    )

    providers_title = models.CharField(max_length=80, default="Financing providers")
    providers_desc = models.CharField(
        max_length=160,
        default="Pick the option that fits your project size and timeline.",
    )
    providers_badge_label = models.CharField(max_length=40, default="Trusted")

    provider_1_title = models.CharField(max_length=80, default="Canadian Financial")
    provider_1_meta = models.CharField(max_length=120, default="Advisor: Canadian Financial team")
    provider_1_desc = models.TextField(
        default="Personalized financing support through Canadian Financial. Great for custom quotes and structured plans."
    )
    provider_1_primary_cta_label = models.CharField(max_length=80, default="Apply with Canadian Financial")
    provider_1_secondary_cta_label = models.CharField(max_length=60, default="How it works")

    provider_2_title = models.CharField(max_length=80, default="Afterpay (via Square)")
    provider_2_meta_prefix = models.CharField(max_length=80, default="Good up to ≈")
    provider_2_meta_amount = models.CharField(max_length=20, default="2,000")
    provider_2_desc = models.TextField(
        default="Split smaller purchases into interest-free payments at checkout. Perfect for parts and minor installs."
    )
    provider_2_primary_cta_label = models.CharField(max_length=60, default="Shop parts")
    provider_2_secondary_cta_label = models.CharField(max_length=60, default="Book an install")

    providers_bottom_primary_cta_label = models.CharField(max_length=40, default="← Home")
    providers_bottom_secondary_cta_label = models.CharField(max_length=80, default="See all services")

    steps_title = models.CharField(max_length=80, default="How financing works")
    steps_desc = models.CharField(max_length=120, default="A simple path from quote to approved build.")
    step_1_title = models.CharField(max_length=80, default="Get your project quote")
    step_1_desc = models.TextField(
        default="Talk to our team about your build or parts install. We’ll outline scope, cost, and timeline."
    )
    step_2_title = models.CharField(max_length=80, default="Apply with a provider")
    step_2_desc = models.TextField(
        default="Use Canadian Financial for larger projects, or Afterpay for smaller purchases."
    )
    step_3_title = models.CharField(max_length=80, default="Choose terms & finalize")
    step_3_desc = models.TextField(
        default="Pick the plan that fits your budget. We coordinate approvals and scheduling."
    )
    step_4_title = models.CharField(max_length=80, default="Build & updates")
    step_4_desc = models.TextField(
        default="We get to work. You’ll receive progress updates in your Client Portal."
    )

    faq_title = models.CharField(max_length=80, default="Good to know")
    faq_desc = models.CharField(max_length=120, default="Quick answers to common questions.")
    faq_1_title = models.CharField(max_length=80, default="Credit checks & approvals")
    faq_1_desc = models.TextField(
        default=(
            "Some providers offer soft credit checks for pre-qualification. Final approval may require a "
            "hard check. Terms and limits depend on your credit profile."
        )
    )
    faq_2_title = models.CharField(max_length=80, default="Project eligibility")
    faq_2_desc = models.TextField(
        default=(
            "Financing can cover parts, labor, coatings, and custom fabrication. We’ll help you structure "
            "the quote to fit provider requirements."
        )
    )
    faq_3_title = models.CharField(max_length=80, default="Afterpay limits")
    faq_3_desc_prefix = models.CharField(
        max_length=140,
        default="Afterpay via Square is typically suitable for purchases up to about",
    )
    faq_3_desc_amount = models.CharField(max_length=20, default="2,000")
    faq_3_desc_suffix = models.CharField(
        max_length=160,
        default="and is best used for smaller jobs and parts orders.",
    )
    faq_4_title = models.CharField(max_length=80, default="Questions?")
    faq_4_desc = models.TextField(
        default="Reach out to our team and we’ll walk you through options and next steps."
    )
    faq_4_cta_label = models.CharField(max_length=60, default="Contact us")

    contact_fab_label = models.CharField(max_length=60, default="Contact us")
    contact_modal_title = models.CharField(max_length=60, default="Contact us")
    contact_close_label = models.CharField(max_length=40, default="Close")
    contact_email_label = models.CharField(max_length=40, default="E-mail")
    contact_phone_label = models.CharField(max_length=40, default="Phone")
    contact_copy_label = models.CharField(max_length=40, default="Copy")
    contact_copy_success_label = models.CharField(max_length=40, default="Copied")
    contact_copy_failed_label = models.CharField(max_length=40, default="Copy failed")
    contact_call_label = models.CharField(max_length=40, default="Call")
    contact_write_email_label = models.CharField(max_length=60, default="Write e-mail")
    contact_text_label = models.CharField(max_length=40, default="Text us")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Financing page copy"
        verbose_name_plural = "Financing page copy"
        ordering = ("singleton_id",)

    def __str__(self) -> str:
        return "Financing page copy"

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_id=1)
        return obj


class AboutPageCopy(models.Model):
    """
    Editable static text for the About / Our Story page.
    """
    singleton_id = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)

    meta_title = models.CharField(max_length=160, default="Bad Guy Motors — Our Story")
    meta_description = models.TextField(
        default=(
            "Family-run fabrication and diesel performance shop crafting racks, bumpers, coatings, "
            "and full builds out of Medicine Hat, AB."
        )
    )

    skip_to_main_label = models.CharField(max_length=120, default="Skip to main content")

    brand_word_white = models.CharField(max_length=40, default="BAD GUY")
    brand_word_red = models.CharField(max_length=40, default="MOTORS")
    brand_tagline = models.CharField(max_length=120, default="CUSTOM BUILDS • INSTALLS • UPGRADES")
    nav_toggle_label = models.CharField(max_length=80, default="Toggle navigation")
    nav_services_label = models.CharField(max_length=40, default="Services")
    nav_client_portal_label = models.CharField(max_length=60, default="Client Portal")
    nav_login_label = models.CharField(max_length=40, default="Login")
    nav_products_label = models.CharField(max_length=40, default="Products")
    nav_merch_label = models.CharField(max_length=40, default="Merch")
    nav_merch_badge = models.CharField(max_length=20, default="Soon")
    nav_dealers_label = models.CharField(max_length=40, default="Dealers")
    nav_financing_label = models.CharField(max_length=40, default="Financing")
    nav_about_label = models.CharField(max_length=40, default="About")

    hero_title = models.CharField(max_length=120, default="From Bad Guys to Builders.")
    hero_lead = models.TextField(
        default=(
            "We took the long road — and turned it into horsepower. Bad Guy Motors is a family-run custom "
            "fabrication and diesel performance shop in Medicine Hat, AB. We build tough parts, tougher rigs, "
            "and a legacy for our kids — from bumpers and racks to fender flares and full builds."
        )
    )
    hero_chip_1 = models.CharField(max_length=60, default="Family owned")
    hero_chip_2 = models.CharField(max_length=60, default="Alberta-made")
    hero_chip_3 = models.CharField(max_length=60, default="Custom only")
    hero_image_alt = models.CharField(max_length=80, default="About hero")
    hero_disclaimer = models.CharField(max_length=140, default="Product may not appear exactly as shown.")

    story_title = models.CharField(max_length=80, default="Our story")
    story_paragraph_1 = models.TextField(
        default=(
            "Co-owners Denim and KC Savoie built Bad Guy Motors after a full 360 — from hard pasts to a focused "
            "future. With two kids and two stepkids, we’re a power couple who put family first and quality second "
            "to none. We set out to create the shop we wished existed: transparent, disciplined, and obsessed "
            "with doing things right."
        )
    )
    story_paragraph_2 = models.TextField(
        default=(
            "Every build is personal: the parts we design, the welds we lay, the timelines we keep. We want "
            "our daughters to see what it means to run a business with grit, integrity, and pride."
        )
    )
    story_photo = models.ImageField(
        upload_to="about/story/",
        blank=True,
        null=True,
        help_text="Optional photo shown in the Our Story section.",
    )
    story_photo_alt = models.CharField(
        max_length=160,
        default="Denim & Kacy at Bad Guy Motors",
    )
    story_photo_placeholder = models.CharField(
        max_length=12,
        default="DK",
        help_text="Fallback initials shown when no photo is uploaded.",
    )
    story_photo_title = models.CharField(max_length=80, default="Denim & Kacy")
    story_photo_subtitle = models.CharField(
        max_length=120,
        default="Co-owners, Bad Guy Motors",
    )
    story_photo_caption = models.CharField(
        max_length=200,
        default="Built on grit, family, and second chances.",
    )

    build_title = models.CharField(max_length=80, default="What we build")
    build_item_1 = models.CharField(max_length=120, default="Bumpers & winch mounts")
    build_item_2 = models.CharField(max_length=120, default="Headache & chase racks")
    build_item_3 = models.CharField(max_length=120, default="Mudflaps & running boards")
    build_item_4 = models.CharField(max_length=120, default="Fender flares")
    build_item_5 = models.CharField(max_length=120, default="Lift kits & 4-link suspensions")
    build_item_6 = models.CharField(max_length=140, default="Diesel performance, tuning & hard parts")
    build_item_7 = models.CharField(max_length=120, default="Body swaps & custom fab")
    build_item_8 = models.CharField(max_length=140, default="Coatings & liners (Armadillo, Smooth Criminal)")

    how_title = models.CharField(max_length=80, default="How we work")
    how_step_1_title = models.CharField(max_length=80, default="Consult & scope")
    how_step_1_desc = models.CharField(max_length=120, default="goals, budget, timeline.")
    how_step_2_title = models.CharField(max_length=80, default="Design & quote")
    how_step_2_desc = models.CharField(max_length=140, default="CAD as needed, milestones, written estimate.")
    how_step_3_title = models.CharField(max_length=80, default="Fabricate & update")
    how_step_3_desc = models.CharField(max_length=140, default="progress pics, approvals, clear comms.")
    how_step_4_title = models.CharField(max_length=80, default="Delivery & aftercare")
    how_step_4_desc = models.CharField(max_length=140, default="test drive, torque check, care guide.")

    rates_title = models.CharField(max_length=80, default="Rates & policies")
    rates_shop_label = models.CharField(max_length=60, default="Shop rate")
    rates_shop_value = models.CharField(max_length=40, default="130/hr")
    rates_cad_label = models.CharField(max_length=60, default="Design/CAD rate")
    rates_cad_value = models.CharField(max_length=40, default="150/hr")
    rates_policies = models.TextField(
        default=(
            "Deposits secure your slot; balance due on delivery.\n"
            "Storage fees may apply for completed items not picked up promptly.\n"
            "Warranty & support — if it isn’t right, we make it right."
        ),
        help_text="One policy per line.",
    )
    rates_policy_1 = models.CharField(
        max_length=160,
        default="Deposits secure your slot; balance due on delivery.",
    )
    rates_policy_2 = models.CharField(
        max_length=180,
        default="Storage fees may apply for completed items not picked up promptly.",
    )
    rates_policy_3 = models.CharField(
        max_length=160,
        default="Warranty & support — if it isn’t right, we make it right.",
    )

    location_title = models.CharField(max_length=80, default="Where to find us")
    location_address = models.TextField(
        default="Bad Guy Motors Inc.\n620 Porcelain Ave SE, Medicine Hat, AB T1A 0C2"
    )
    location_note = models.CharField(
        max_length=160,
        default="Open by appointment. Book online to lock your time.",
    )
    location_primary_cta_label = models.CharField(max_length=60, default="Book a service")
    location_secondary_cta_label = models.CharField(max_length=60, default="Client portal")

    amvic_title = models.CharField(max_length=80, default="Licensed by AMVIC")
    amvic_description = models.CharField(
        max_length=200,
        default="Bad Guy Motors is a licensed automotive business under the Alberta Motor Vehicle Industry Council.",
    )

    contact_fab_label = models.CharField(max_length=60, default="Contact us")
    contact_modal_title = models.CharField(max_length=60, default="Contact us")
    contact_close_label = models.CharField(max_length=40, default="Close")
    contact_email_label = models.CharField(max_length=40, default="E-mail")
    contact_phone_label = models.CharField(max_length=40, default="Phone")
    contact_copy_label = models.CharField(max_length=40, default="Copy")
    contact_copy_success_label = models.CharField(max_length=40, default="Copied")
    contact_copy_failed_label = models.CharField(max_length=40, default="Copy failed")
    contact_call_label = models.CharField(max_length=40, default="Call")
    contact_write_email_label = models.CharField(max_length=60, default="Write e-mail")
    contact_text_label = models.CharField(max_length=40, default="Text us")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "About page copy"
        verbose_name_plural = "About page copy"
        ordering = ("singleton_id",)

    def __str__(self) -> str:
        return "About page copy"

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_id=1)
        return obj


class DealerStatusPageCopy(models.Model):
    """
    Editable static text for the dealer portal/status page.
    """
    singleton_id = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)

    meta_title = models.CharField(max_length=160, default="Dealer Portal — BGM Customs")
    meta_description = models.TextField(
        default="Track dealer tier, benefits, and requirements for the BGM Customs wholesale program."
    )

    brand_word_white = models.CharField(max_length=40, default="BAD GUY")
    brand_word_red = models.CharField(max_length=40, default="MOTORS")
    header_badge_label = models.CharField(max_length=60, default="Dealer Portal")
    nav_store_label = models.CharField(max_length=40, default="Store")
    nav_cart_label = models.CharField(max_length=40, default="Cart")
    nav_dealers_label = models.CharField(max_length=40, default="Dealers")
    nav_services_label = models.CharField(max_length=60, default="Services")

    hero_eyebrow = models.CharField(max_length=60, default="BGM Customs")
    hero_title = models.CharField(max_length=120, default="Dealer workspace")
    hero_lead = models.TextField(
        default=(
            "Track your approval status, understand the tier ladder, and jump straight into the catalog with "
            "your negotiated pricing."
        )
    )
    hero_tier_label_prefix = models.CharField(max_length=40, default="Tier:")
    tier_default_label = models.CharField(max_length=60, default="Standard")
    hero_discount_suffix = models.CharField(max_length=40, default="off catalog")
    hero_primary_cta_label = models.CharField(max_length=60, default="Browse catalog")
    hero_secondary_cta_label = models.CharField(max_length=40, default="Open cart")

    hero_stat_dealer_since_label = models.CharField(max_length=60, default="Dealer since")
    hero_stat_pending_label = models.CharField(max_length=80, default="Pending activation")
    hero_stat_lifetime_spend_label = models.CharField(max_length=80, default="Lifetime spend")
    hero_stat_next_tier_label = models.CharField(max_length=80, default="Next tier target")
    hero_stat_next_tier_suffix = models.CharField(max_length=60, default="to unlock")
    hero_stat_top_tier_label = models.CharField(max_length=80, default="Top tier unlocked")
    hero_stat_top_tier_value = models.CharField(max_length=120, default="Enjoy the max discount")
    hero_disclaimer = models.CharField(
        max_length=140,
        default="Product may not appear exactly as shown.",
    )

    account_overview_title = models.CharField(max_length=80, default="Account overview")
    account_overview_badge_label = models.CharField(max_length=40, default="Active")
    account_metric_tier_label = models.CharField(max_length=40, default="Tier")
    account_metric_discount_label = models.CharField(max_length=40, default="Discount")
    account_metric_lifetime_spend_label = models.CharField(max_length=60, default="Lifetime spend")
    account_metric_last_review_label = models.CharField(max_length=60, default="Last review")

    progress_title = models.CharField(max_length=80, default="Progress to next tier")
    progress_max_tier_badge = models.CharField(max_length=80, default="Max tier unlocked")
    progress_top_tier_label = models.CharField(max_length=40, default="Top tier")

    orders_title = models.CharField(max_length=60, default="Orders")
    orders_badge_suffix = models.CharField(max_length=20, default="total")
    orders_open_label = models.CharField(max_length=40, default="Open")
    orders_completed_label = models.CharField(max_length=40, default="Completed")
    orders_most_recent_label = models.CharField(max_length=60, default="Most recent")
    orders_cta_label = models.CharField(max_length=40, default="Place order")

    resources_title = models.CharField(max_length=60, default="Resources")
    resource_1_title = models.CharField(max_length=80, default="Dealer price sheet")
    resource_1_desc = models.CharField(
        max_length=160,
        default="Download the latest catalog with your discount baked in.",
    )
    resource_1_cta_label = models.CharField(max_length=60, default="Open catalog")
    resource_2_title = models.CharField(max_length=80, default="Support desk")
    resource_2_desc = models.CharField(
        max_length=180,
        default="Need to escalate an order or request marketing assets? Reach out.",
    )
    resource_2_cta_label = models.CharField(max_length=60, default="Contact support")
    resource_3_title = models.CharField(max_length=80, default="Dealer policy")
    resource_3_desc = models.CharField(
        max_length=180,
        default="Review the playbook covering terms, logistics, and reporting cadence.",
    )
    resource_3_cta_label = models.CharField(max_length=60, default="View policy")

    application_status_title = models.CharField(max_length=80, default="Application status")
    application_status_not_submitted_badge = models.CharField(max_length=60, default="Not submitted")
    application_pending_callout = models.TextField(
        default=(
            "Thanks for applying. Your submission is in the review queue. We typically respond within 2 business days."
        )
    )
    application_rejected_callout = models.TextField(
        default="The previous request was declined. Feel free to update your details and submit a new application."
    )
    application_approved_callout = models.TextField(
        default="Approved — we are finalizing onboarding. Expect an activation email shortly."
    )
    application_none_callout = models.TextField(
        default=(
            "You have not submitted a dealer request yet. Tell us about your business and projected volume to "
            "unlock wholesale pricing."
        )
    )
    application_metric_business_label = models.CharField(max_length=60, default="Business")
    application_metric_tier_label = models.CharField(max_length=60, default="Requested tier")
    application_metric_submitted_label = models.CharField(max_length=60, default="Submitted")
    application_contact_cta_label = models.CharField(
        max_length=120,
        default="Need to update your data? Contact us",
    )
    application_apply_cta_label = models.CharField(max_length=40, default="Apply now")
    application_reapply_cta_label = models.CharField(max_length=40, default="Reapply")

    tier_ladder_title = models.CharField(max_length=60, default="Tier ladder")
    tier_ladder_badge_label = models.CharField(max_length=80, default="Transparent thresholds")
    tier_table_tier_label = models.CharField(max_length=40, default="Tier")
    tier_table_min_spend_label = models.CharField(max_length=80, default="Minimum spend")
    tier_table_discount_label = models.CharField(max_length=60, default="Discount")
    tier_table_notes_label = models.CharField(max_length=60, default="Notes")
    tier_empty_label = models.CharField(max_length=120, default="Tier configuration is coming soon.")

    timeline_title = models.CharField(max_length=80, default="Lifecycle timeline")
    timeline_in_progress_label = models.CharField(max_length=60, default="In progress")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Dealer portal copy"
        verbose_name_plural = "Dealer portal copy"
        ordering = ("singleton_id",)

    def __str__(self) -> str:
        return "Dealer portal copy"

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_id=1)
        return obj


class EmailTemplateSettings(models.Model):
    """
    Global defaults used across all email templates.
    """
    singleton_id = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    brand_name = models.CharField(
        max_length=120,
        blank=True,
        help_text="Optional override for SITE_BRAND_NAME when sending emails.",
    )
    brand_tagline = models.CharField(
        max_length=140,
        blank=True,
        help_text="Optional override for SITE_BRAND_TAGLINE in email headers/footers.",
    )
    company_address = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional override for COMPANY_ADDRESS in email footers.",
    )
    company_phone = models.CharField(
        max_length=40,
        blank=True,
        help_text="Optional override for COMPANY_PHONE in email footers.",
    )
    company_website = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional override for COMPANY_WEBSITE in email footers and CTA defaults.",
    )
    support_email = models.EmailField(
        blank=True,
        help_text="Optional override for SUPPORT_EMAIL placeholders.",
    )
    accent_color = models.CharField(
        max_length=20,
        blank=True,
        help_text="Optional override for EMAIL_ACCENT_COLOR (hex like #d50000).",
    )
    dark_color = models.CharField(
        max_length=20,
        blank=True,
        help_text="Optional override for EMAIL_DARK_COLOR (hex like #0b0b0c).",
    )
    bg_color = models.CharField(
        max_length=20,
        blank=True,
        help_text="Optional override for EMAIL_BG_COLOR (hex like #0b0b0c).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Email template settings"
        verbose_name_plural = "Email template settings"
        ordering = ("singleton_id",)

    def __str__(self) -> str:
        return "Email template settings"

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_id=1)
        return obj


class EmailTemplate(models.Model):
    class TemplateSlug(models.TextChoices):
        APPOINTMENT_CONFIRMATION = "appointment_confirmation", "Appointment confirmation"
        ORDER_CONFIRMATION = "order_confirmation", "Order confirmation"
        ORDER_STATUS_PROCESSING = "order_status_processing", "Order status: processing"
        ORDER_STATUS_SHIPPED = "order_status_shipped", "Order status: shipped"
        ORDER_STATUS_COMPLETED = "order_status_completed", "Order status: completed"
        ORDER_STATUS_CANCELLED = "order_status_cancelled", "Order status: cancelled"
        ABANDONED_CART_1 = "abandoned_cart_1", "Abandoned cart (1st)"
        ABANDONED_CART_2 = "abandoned_cart_2", "Abandoned cart (2nd)"
        ABANDONED_CART_3 = "abandoned_cart_3", "Abandoned cart (3rd)"
        SITE_NOTICE_WELCOME = "site_notice_welcome", "Email signup: welcome code"
        SITE_NOTICE_FOLLOWUP_2 = "site_notice_followup_2", "Email signup: 24h follow-up"
        SITE_NOTICE_FOLLOWUP_3 = "site_notice_followup_3", "Email signup: 3-day follow-up"
        ORDER_REVIEW_REQUEST = "order_review_request", "Order review request"
        FITMENT_REQUEST_INTERNAL = "fitment_request_internal", "Custom fitment request (internal)"

    slug = models.SlugField(max_length=80, unique=True, choices=TemplateSlug.choices)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)

    subject = models.CharField(max_length=180)
    preheader = models.CharField(max_length=180, blank=True)
    title = models.CharField(max_length=140)
    greeting = models.CharField(max_length=160, blank=True)
    intro = models.TextField(
        blank=True,
        help_text="One sentence per line. These lines appear near the top of the email.",
    )
    notice_title = models.CharField(max_length=120, blank=True)
    notice = models.TextField(
        blank=True,
        help_text="Optional callout. One sentence per line.",
    )
    footer = models.TextField(
        blank=True,
        help_text="One sentence per line. Appears at the bottom of the email.",
    )
    cta_label = models.CharField(max_length=80, blank=True)
    cta_url = models.CharField(
        max_length=240,
        blank=True,
        help_text="Optional button link override. Supports placeholders like {company_website}.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Email template"
        verbose_name_plural = "Email templates"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class EmailSubscriber(models.Model):
    class Source(models.TextChoices):
        IMPORT = "import", "Imported list"
        MANUAL = "manual", "Manual entry"

    email = models.EmailField(unique=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    is_active = models.BooleanField(default=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="email_subscribers_added",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Email subscriber"
        verbose_name_plural = "Email subscribers"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)


class EmailCampaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        PARTIAL = "partial", "Sent with errors"
        FAILED = "failed", "Failed"

    name = models.CharField(max_length=160)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    from_email = models.EmailField(blank=True)

    subject = models.CharField(max_length=180)
    preheader = models.CharField(max_length=180, blank=True)
    title = models.CharField(max_length=140)
    greeting = models.CharField(max_length=160, blank=True)
    intro = models.TextField(
        blank=True,
        help_text="One sentence per line. These lines appear near the top of the email.",
    )
    notice_title = models.CharField(max_length=120, blank=True)
    notice = models.TextField(
        blank=True,
        help_text="Optional callout. One sentence per line.",
    )
    footer = models.TextField(
        blank=True,
        help_text="One sentence per line. Appears at the bottom of the email.",
    )
    cta_label = models.CharField(max_length=80, blank=True)
    cta_url = models.URLField(max_length=500, blank=True)

    include_subscribers = models.BooleanField(default=True)
    include_registered_users = models.BooleanField(
        default=True,
        help_text="Only users who opted into marketing emails are included.",
    )

    recipients_total = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    send_started_at = models.DateTimeField(null=True, blank=True)
    send_completed_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="email_campaigns_sent",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Email campaign"
        verbose_name_plural = "Email campaigns"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return self.name


class EmailCampaignRecipient(models.Model):
    class Source(models.TextChoices):
        SUBSCRIBER = "subscriber", "Subscriber list"
        USER = "user", "Registered user"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    campaign = models.ForeignKey(EmailCampaign, on_delete=models.CASCADE)
    email = models.EmailField()
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="email_campaign_recipients",
    )
    source = models.CharField(max_length=16, choices=Source.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    error_message = models.CharField(max_length=255, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Email campaign recipient"
        verbose_name_plural = "Email campaign recipients"
        ordering = ("-created_at",)
        unique_together = ("campaign", "email")
        indexes = [
            models.Index(fields=["campaign", "status"]),
            models.Index(fields=["email"]),
        ]

    def __str__(self) -> str:
        return f"{self.email} ({self.campaign})"

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)


class EmailSendLog(models.Model):
    """
    Lightweight log of outbound emails for auditing and troubleshooting.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email_type = models.CharField(max_length=120, db_index=True)
    subject = models.CharField(max_length=200, blank=True)
    from_email = models.EmailField(blank=True)
    recipients = models.JSONField(default=list, blank=True)
    recipient_count = models.PositiveIntegerField(default=0)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-sent_at",)
        verbose_name = "Email send log"
        verbose_name_plural = "Email send logs"
        indexes = [
            models.Index(fields=["email_type"]),
            models.Index(fields=["sent_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.email_type} ({self.recipient_count})"


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
            try:
                return static(self.static_path)
            except Exception:
                try:
                    if finders.find(self.static_path):
                        return f"{settings.STATIC_URL}{self.static_path.lstrip('/')}"
                except Exception:
                    pass
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
        SERVICES = "services", "Services page"
        STORE = "store", "Store page"
        MERCH = "merch", "Merch page"
        FINANCING = "financing", "Financing page"
        ABOUT = "about", "About page"
        BRAKE_SUSPENSION = "brake_suspension", "Brake & Suspension page"
        WHEEL_TIRE_SERVICE = "wheel_tire_service", "Wheel & Tire Service page"
        PERFORMANCE_TUNING = "performance_tuning", "Performance Tuning page"
        ELECTRICAL_WORK = "electrical_work", "Electrical Work page"
        PROJECT_JOURNAL = "project_journal", "Project journal"

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
    style_overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text="Optional per-page typography overrides (size, weight, spacing).",
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


class TopbarSettings(models.Model):
    """
    Global navigation bar styling controls exposed in the admin UI.
    """
    singleton_id = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)

    brand_font = models.ForeignKey(
        FontPreset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="topbar_brand_settings",
        help_text="Font used for the business name in the top bar.",
    )
    brand_word_white_font = models.ForeignKey(
        FontPreset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="topbar_brand_word_white_settings",
        help_text="Optional font override for the first brand word.",
    )
    brand_word_red_font = models.ForeignKey(
        FontPreset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="topbar_brand_word_red_settings",
        help_text="Optional font override for the third brand word.",
    )
    brand_word_middle_font = models.ForeignKey(
        FontPreset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="topbar_brand_word_middle_settings",
        help_text="Optional font override for the middle brand word.",
    )
    nav_font = models.ForeignKey(
        FontPreset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="topbar_nav_settings",
        help_text="Font used for navigation links and badges.",
    )
    tagline_word_1_font = models.ForeignKey(
        FontPreset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="topbar_tagline_word_1_settings",
        help_text="Optional font override for the first tagline word.",
    )
    tagline_word_2_font = models.ForeignKey(
        FontPreset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="topbar_tagline_word_2_settings",
        help_text="Optional font override for the second tagline word.",
    )
    tagline_word_3_font = models.ForeignKey(
        FontPreset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="topbar_tagline_word_3_settings",
        help_text="Optional font override for the third tagline word.",
    )

    tagline_word_1_text = models.CharField(
        max_length=40,
        blank=True,
        default="",
        help_text="Optional override for the first tagline word.",
    )
    tagline_word_2_text = models.CharField(
        max_length=40,
        blank=True,
        default="",
        help_text="Optional override for the second tagline word.",
    )
    tagline_word_3_text = models.CharField(
        max_length=40,
        blank=True,
        default="",
        help_text="Optional override for the third tagline word.",
    )

    brand_size_desktop = models.CharField(
        max_length=32,
        default="clamp(1.25rem, 2.1vw, 1.7rem)",
        help_text="CSS font-size value for the brand text (desktop).",
    )
    brand_weight = models.CharField(
        max_length=16,
        default="400",
        help_text="CSS font-weight for the brand text.",
    )
    brand_letter_spacing = models.CharField(
        max_length=16,
        default="0",
        help_text="CSS letter-spacing for the brand text.",
    )
    brand_transform = models.CharField(
        max_length=16,
        default="none",
        help_text="CSS text-transform for the brand text.",
    )

    nav_size = models.CharField(
        max_length=16,
        default="0.95rem",
        help_text="CSS font-size for nav links (mobile).",
    )
    nav_size_desktop = models.CharField(
        max_length=16,
        default="1.05rem",
        help_text="CSS font-size for nav links (desktop).",
    )
    padding_y_desktop = models.CharField(
        max_length=16,
        default="0.95rem",
        help_text="CSS padding-block for the top bar (desktop).",
    )
    order_brand = models.CharField(
        max_length=8,
        default="1",
        help_text="CSS order for the brand block.",
    )
    order_tagline = models.CharField(
        max_length=8,
        default="2",
        help_text="CSS order for the tagline block.",
    )
    order_nav = models.CharField(
        max_length=8,
        default="3",
        help_text="CSS order for the navigation block.",
    )
    brand_word_1_color = models.CharField(
        max_length=24,
        blank=True,
        default="",
        help_text="CSS color for the first brand word.",
    )
    brand_word_2_color = models.CharField(
        max_length=24,
        blank=True,
        default="",
        help_text="CSS color for the second brand word.",
    )
    brand_word_3_color = models.CharField(
        max_length=24,
        blank=True,
        default="",
        help_text="CSS color for the third brand word.",
    )
    brand_word_1_size = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-size for the first brand word.",
    )
    brand_word_2_size = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-size for the second brand word.",
    )
    brand_word_3_size = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-size for the third brand word.",
    )
    brand_word_1_weight = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-weight for the first brand word.",
    )
    brand_word_2_weight = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-weight for the second brand word.",
    )
    brand_word_3_weight = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-weight for the third brand word.",
    )
    brand_word_1_style = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-style for the first brand word (normal/italic).",
    )
    brand_word_2_style = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-style for the second brand word (normal/italic).",
    )
    brand_word_3_style = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-style for the third brand word (normal/italic).",
    )
    tagline_word_1_color = models.CharField(
        max_length=24,
        blank=True,
        default="",
        help_text="CSS color for the first tagline word.",
    )
    tagline_word_2_color = models.CharField(
        max_length=24,
        blank=True,
        default="",
        help_text="CSS color for the second tagline word.",
    )
    tagline_word_3_color = models.CharField(
        max_length=24,
        blank=True,
        default="",
        help_text="CSS color for the third tagline word.",
    )
    tagline_word_1_size = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-size for the first tagline word.",
    )
    tagline_word_2_size = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-size for the second tagline word.",
    )
    tagline_word_3_size = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-size for the third tagline word.",
    )
    tagline_word_1_weight = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-weight for the first tagline word.",
    )
    tagline_word_2_weight = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-weight for the second tagline word.",
    )
    tagline_word_3_weight = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-weight for the third tagline word.",
    )
    tagline_word_1_style = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-style for the first tagline word (normal/italic).",
    )
    tagline_word_2_style = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-style for the second tagline word (normal/italic).",
    )
    tagline_word_3_style = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="CSS font-style for the third tagline word (normal/italic).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Topbar settings"
        verbose_name_plural = "Topbar settings"
        ordering = ("singleton_id",)

    def __str__(self) -> str:
        return "Topbar settings"

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_id=1)
        return obj

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
    overview = models.TextField(
        blank=True,
        help_text="High-level summary for the gallery overview panel.",
    )
    parts = models.TextField(
        blank=True,
        help_text="Parts list or components used (one per line).",
    )
    customizations = models.TextField(
        blank=True,
        help_text="Custom fabrication, tuning, or unique upgrades (one per line).",
    )
    backstory = models.TextField(
        blank=True,
        help_text="Narrative backstory for the build.",
    )
    body = models.TextField()
    cover_image = models.ImageField(upload_to="project-journal/", blank=True, null=True)
    before_gallery = models.JSONField(
        default=list,
        blank=True,
        help_text="List of before photos as JSON (e.g. [{\"url\":\"...\",\"alt\":\"...\"}] or [\"url1\",\"url2\"]).",
    )
    after_gallery = models.JSONField(
        default=list,
        blank=True,
        help_text="List of after photos as JSON (e.g. [{\"url\":\"...\",\"alt\":\"...\"}] or [\"url1\",\"url2\"]).",
    )
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

class ProjectJournalPhoto(models.Model):
    class Kind(models.TextChoices):
        BEFORE = "before", "Before"
        AFTER = "after", "After"

    entry = models.ForeignKey(
        ProjectJournalEntry,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    image = models.ImageField(upload_to="project-journal/photos/")
    alt_text = models.CharField(max_length=140, blank=True)
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Lower numbers show first.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Project journal photo"
        verbose_name_plural = "Project journal photos"
        ordering = ("sort_order", "created_at")

    def __str__(self) -> str:
        title = self.entry.title if self.entry_id else "Project journal photo"
        return f"{title} ({self.get_kind_display()})"

class HeroImage(models.Model):
    """
    Configurable hero/cover image for high-visibility marketing sections.
    """
    class Location(models.TextChoices):
        HOME = "home", "Home hero"
        HOME_CAROUSEL_A = "home-carousel-a", "Home hero carousel — slide 1"
        HOME_CAROUSEL_B = "home-carousel-b", "Home hero carousel — slide 2"
        HOME_CAROUSEL_C = "home-carousel-c", "Home hero carousel — slide 3"
        HOME_CAROUSEL_D = "home-carousel-d", "Home hero carousel — slide 4"
        HOME_GALLERY_A = "home-gallery-a", "Home gallery — slot 1"
        HOME_GALLERY_B = "home-gallery-b", "Home gallery — slot 2"
        HOME_GALLERY_C = "home-gallery-c", "Home gallery — slot 3"
        HOME_GALLERY_D = "home-gallery-d", "Home gallery — slot 4"
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
    email_product_updates = models.BooleanField(default=False)
    email_service_updates = models.BooleanField(default=False)
    admin_notification_disabled_sections = models.JSONField(
        default=list,
        blank=True,
        help_text="Admin notification section keys disabled for this user.",
    )
    how_heard = models.CharField(max_length=32, choices=HowHeard.choices, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    email_verification_sent_at = models.DateTimeField(null=True, blank=True)

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


class LeadSubmissionEvent(models.Model):
    """
    Non-PII logging for public lead/signup submissions.
    """

    class FormType(models.TextChoices):
        SITE_NOTICE = ("site_notice", "Site notice signup")
        SERVICE_LEAD = ("service_lead", "Service lead")

    class Outcome(models.TextChoices):
        ACCEPTED = ("accepted", "Accepted")
        SUSPECTED = ("suspected", "Accepted (suspected)")
        BLOCKED = ("blocked", "Blocked")
        RATE_LIMITED = ("rate_limited", "Rate limited")
        REJECTED = ("rejected", "Rejected")

    form_type = models.CharField(max_length=40, choices=FormType.choices, db_index=True)
    outcome = models.CharField(max_length=40, choices=Outcome.choices, db_index=True)
    success = models.BooleanField(default=False)
    suspicion_score = models.PositiveSmallIntegerField(default=0)
    validation_errors = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    ip_location = models.CharField(max_length=255, blank=True)
    user_agent = models.TextField(blank=True)
    accept_language = models.CharField(max_length=512, blank=True)
    referer = models.CharField(max_length=600, blank=True)
    origin = models.CharField(max_length=300, blank=True)
    path = models.CharField(max_length=300, blank=True)
    session_key_hash = models.CharField(max_length=64, blank=True)
    session_first_seen_at = models.DateTimeField(null=True, blank=True)
    time_on_page_ms = models.PositiveIntegerField(null=True, blank=True)
    cf_country = models.CharField(max_length=12, blank=True)
    cf_asn = models.CharField(max_length=40, blank=True)
    cf_asn_org = models.CharField(max_length=200, blank=True)
    flags = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["form_type", "created_at"]),
            models.Index(fields=["outcome", "created_at"]),
            models.Index(fields=["ip_address", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_form_type_display()} • {self.get_outcome_display()} @ {self.created_at:%Y-%m-%d %H:%M:%S}"


class LandingPageReview(models.Model):
    """
    Marketing review snippets shown on specific landing pages.
    """

    class Page(models.TextChoices):
        HOME = ("home", "Home page")
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
    ip_location = models.CharField(max_length=255, blank=True)
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
