from pathlib import Path
import os
import dj_database_url
from decouple import config, Csv  # оставил, если используешь .env локально

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Основное ─────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
DEBUG = os.getenv("DEBUG", "False") == "True"

ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "*").split(",") if h.strip()]

# ── Бренд и маркетинг ───────────────────────────────────────────────────
SITE_BRAND_NAME = os.getenv("SITE_BRAND_NAME", "BGM Customs")
SITE_BRAND_TAGLINE = os.getenv("SITE_BRAND_TAGLINE", "Performance builds and outlaw styling out of Calgary.")
SITE_DEFAULT_DESCRIPTION = os.getenv(
    "SITE_DEFAULT_DESCRIPTION",
    "BGM Customs delivers bespoke performance builds, detailing and premium parts sourcing for enthusiasts across North America.",
)
SITE_DEFAULT_IMAGE = os.getenv("SITE_DEFAULT_IMAGE", "/static/img/bad-guy-preview.png")
SITE_ORG_LOGO = os.getenv("SITE_ORG_LOGO", "/static/img/bad-guy-preview.png")
SITE_ORG_SAME_AS = [url.strip() for url in os.getenv("SITE_ORG_SAME_AS", "").split(",") if url.strip()]
MARKETING = {
    "site_name": SITE_BRAND_NAME,
    "tagline": SITE_BRAND_TAGLINE,
    "default_description": SITE_DEFAULT_DESCRIPTION,
    "default_image": SITE_DEFAULT_IMAGE,
    "organization_logo": SITE_ORG_LOGO,
    "organization_same_as": SITE_ORG_SAME_AS,
    "google_tag_manager_id": os.getenv("GOOGLE_TAG_MANAGER_ID", "GTM-M7FTNXV6"),
    "google_ads_id": os.getenv("GOOGLE_ADS_ID", ""),
    "google_ads_conversion_label": os.getenv("GOOGLE_ADS_CONVERSION_LABEL", ""),
    "google_ads_send_page_view": os.getenv("GOOGLE_ADS_SEND_PAGE_VIEW", "True") == "True",
}

# ── Currency ──────────────────────────────────────────────────────────────
DEFAULT_CURRENCY_CODE = os.getenv("DEFAULT_CURRENCY_CODE", "CAD")
DEFAULT_CURRENCY_SYMBOL = os.getenv("DEFAULT_CURRENCY_SYMBOL", "$")

# ── Приложения ───────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "phonenumbers",
    "accounts",
    "core",
    "notifications",
    "dal",
    "dal_select2",
    # "storages",
    "jazzmin",

    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",

    "whitenoise.runserver_nostatic",   # для локалки без дубля статики
    "django.contrib.staticfiles",
    "store",
]

# ── Middleware ───────────────────────────────────────────────────────────
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # сразу после Security
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.VisitorAnalyticsMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # "accounts.middleware.ForceAdminReAuthMiddleware",
]

ROOT_URLCONF = "booking.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "booking" / "templates", BASE_DIR / "templates"],


        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors_core.hero_media",
                "core.context_processors_core.dealer_portal",
                "core.context_processors_core.currency",
                "core.context_processors_core.marketing_tags",
            ],
        },
    },
]

WSGI_APPLICATION = "booking.wsgi.application"
TEMPLATES[0]["OPTIONS"].setdefault("builtins", []).append("django.templatetags.static")

# ── База данных ──────────────────────────────────────────────────────────
# В проде Dokku подставит DATABASE_URL из `dokku postgres:link`.
# Локально используем твою PostgreSQL-конфигурацию по умолчанию.
DEFAULT_LOCAL_DB_URL = (
    "postgres://bgm:malva_strong_password@localhost:5432/bgm_db"
)
DATABASES = {
    "default": dj_database_url.config(
        default=os.getenv("DATABASE_URL", DEFAULT_LOCAL_DB_URL),
        conn_max_age=600,
        ssl_require=False,
    )
}

# ── Пароли ───────────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ── Локаль/время ─────────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Edmonton"
USE_I18N = True
USE_TZ = True

# ── Статика/медиа ────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = os.getenv("STATIC_ROOT", BASE_DIR / "staticfiles")
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []

MEDIA_URL = "/media/"
MEDIA_ROOT = os.getenv("MEDIA_ROOT", BASE_DIR / "media")

# STORAGES = {
#     "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
#     "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
# }

# S3 для медиа включается переменной USE_S3_MEDIA=1
if os.getenv("USE_S3_MEDIA") == "1":
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME", "ca-central-1")
    AWS_S3_ENDPOINT_URL = os.getenv("AWS_S3_ENDPOINT_URL")  # для совместимых S3
    AWS_QUERYSTRING_AUTH = False
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = None
    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
    # MEDIA_URL автоматически сформируется boto3, но можно переопределить:
    if AWS_S3_ENDPOINT_URL and AWS_STORAGE_BUCKET_NAME:
        MEDIA_URL = f"{AWS_S3_ENDPOINT_URL.rstrip('/')}/{AWS_STORAGE_BUCKET_NAME}/"

# ── Безопасность продакшна ──────────────────────────────────────────────
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "True") == "True"

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h]

# ── Jazzmin (как было) ───────────────────────────────────────────────────
ADMIN_SIDEBAR_SECTIONS = [
    {
        "label": "Operations",
        "icon": "fas fa-gauge-high",
        "groups": [
            {
                "label": "Appointments",
                "icon": "fas fa-calendar-check",
                "items": [
                    {"model": "core.Appointment", "label": "Calendar"},
                    {"model": "core.AppointmentStatus", "label": "Status Library"},
                    {"model": "core.AppointmentStatusHistory", "label": "Status Timeline"},
                    {"model": "core.AppointmentPrepayment", "label": "Collected Prepayments"},
                ],
            },
            {
                "label": "Staffing",
                "icon": "fas fa-user-gear",
                "items": [
                    {"model": "core.MasterAvailability", "label": "Availability"},
                    {"model": "core.MasterProfile", "label": "Team Profiles"},
                    {"model": "core.ServiceMaster", "label": "Service Assignment"},
                    {"model": "core.MasterRoom", "label": "Rooms & Bays"},
                ],
            },
            {
                "label": "Payments",
                "icon": "fas fa-sack-dollar",
                "items": [
                    {"model": "core.Payment"},
                    {"model": "core.PaymentStatus", "label": "Payment Status"},
                    {"model": "core.PaymentMethod", "label": "Payment Methods"},
                    {"model": "core.PrepaymentOption", "label": "Prepayment Options"},
                ],
            },
            {
                "label": "Promotions",
                "icon": "fas fa-tags",
                "items": [
                    {"model": "core.ServiceDiscount", "label": "Service Discounts"},
                    {"model": "core.PromoCode", "label": "Promo Codes"},
                    {"model": "core.AppointmentPromoCode", "label": "Appointment Promo Codes"},
                ],
            },
        ],
    },
    {
        "label": "Clients",
        "icon": "fas fa-users",
        "groups": [
            {
                "label": "Client Records",
                "icon": "fas fa-address-card",
                "items": [
                    {"model": "core.UserProfile", "label": "Client Profiles"},
                    {"model": "core.ClientFile", "label": "Client Files"},
                    {"model": "core.ClientReview", "label": "Reviews"},
                    {"model": "core.ClientSource", "label": "Lead Sources"},
                ],
            },
            {
                "label": "Dealer Program",
                "icon": "fas fa-user-shield",
                "items": [
                    {"model": "core.DealerTierLevel", "label": "Tier Levels"},
                    {"model": "core.DealerApplication", "label": "Applications"},
                ],
            },
        ],
    },
    {
        "label": "Storefront",
        "icon": "fas fa-store",
        "groups": [
            {
                "label": "Catalog",
                "icon": "fas fa-box-open",
                "items": [
                    {"model": "store.Category", "label": "Product Categories"},
                    {"model": "store.Product"},
                    {"model": "store.ProductImage", "label": "Product Gallery"},
                    {"model": "store.ProductOption", "label": "Product Options"},
                ],
            },
            {
                "label": "Vehicles & Fitment",
                "icon": "fas fa-car-side",
                "items": [
                    {"model": "store.CarMake", "label": "Car Makes"},
                    {"model": "store.CarModel", "label": "Car Models"},
                    {"model": "store.CustomFitmentRequest", "label": "Fitment Requests"},
                ],
            },
            {
                "label": "Orders",
                "icon": "fas fa-cart-shopping",
                "items": [
                    {"model": "store.Order", "label": "Orders"},
                    {"model": "store.OrderItem", "label": "Order Items"},
                ],
            },
        ],
    },
    {
        "label": "Automation",
        "icon": "fas fa-robot",
        "groups": [
            {
                "label": "Telegram Bot",
                "icon": "fas fa-paper-plane",
                "items": [
                    {"model": "notifications.TelegramContact", "label": "Contacts"},
                    {"model": "notifications.TelegramBotSettings", "label": "Bot Settings"},
                    {"model": "notifications.TelegramReminder", "label": "Reminders"},
                    {"model": "notifications.TelegramMessageLog", "label": "Delivery Log"},
                ],
            },
        ],
    },
    {
        "label": "Content & Insights",
        "icon": "fas fa-bullhorn",
        "groups": [
            {
                "label": "Services & Packages",
                "icon": "fas fa-screwdriver-wrench",
                "items": [
                    {"model": "core.ServiceCategory", "label": "Service Categories"},
                    {"model": "core.Service"},
                ],
            },
            {
                "label": "Website",
                "icon": "fas fa-globe",
                "items": [
                    {"model": "core.LegalPage", "label": "Legal Pages"},
                    {"model": "core.FontPreset", "label": "Font Library"},
                    {"model": "core.PageFontSetting", "label": "Page Fonts"},
                    {"model": "core.LandingPageReview", "label": "Landing Reviews"},
                    {"model": "core.ProjectJournalEntry", "label": "Project Journal"},
                    {"model": "core.HeroImage", "label": "Hero Assets"},
                ],
            },
            {
                "label": "Messaging",
                "icon": "fas fa-bell",
                "items": [
                    {"model": "core.Notification", "label": "Notifications"},
                ],
            },
            {
                "label": "Analytics",
                "icon": "fas fa-chart-line",
                "items": [
                    {"model": "core.VisitorSession", "label": "Visitor Sessions"},
                    {"model": "core.PageView", "label": "Page Views"},
                ],
            },
        ],
    },
    {
        "label": "System",
        "icon": "fas fa-shield-halved",
        "groups": [
            {
                "label": "Access Control",
                "icon": "fas fa-user-lock",
                "items": [
                    {"model": "auth.User", "label": "Users"},
                    {"model": "auth.Group", "label": "Groups"},
                    {"model": "core.Role", "label": "Roles"},
                    {"model": "core.UserRole", "label": "Role Assignments"},
                ],
            },
        ],
    },
]

JAZZMIN_SETTINGS = {
    "site_title": "BGM Admin",
    "site_header": "BGM",
    "welcome_sign": "Welcome to BGM",
    "copyright": "BGM © 2025",
    "search_model": ["auth.User"],
    "show_sidebar": True,
    "navigation_expanded": False,
    "show_ui_builder": False,
    "hide_models": [],
    "topmenu_links": [{"name": "Webpage", "url": "/", "permissions": ["auth.view_user"]}],
    "icons": {
        "auth.User": "fas fa-user",
        "auth.Group": "fas fa-users-cog",
        "core.Appointment": "fas fa-calendar-check",
        "core.AppointmentStatus": "fas fa-circle-dot",
        "core.AppointmentStatusHistory": "fas fa-wave-square",
        "core.AppointmentPrepayment": "fas fa-coins",
        "core.AppointmentPromoCode": "fas fa-ticket",
        "core.ClientFile": "fas fa-folder-open",
        "core.ClientReview": "fas fa-comments",
        "core.ClientSource": "fas fa-bullseye",
        "core.DealerApplication": "fas fa-user-check",
        "core.DealerTierLevel": "fas fa-medal",
        "core.HeroImage": "fas fa-panorama",
        "core.FontPreset": "fas fa-font",
        "core.PageFontSetting": "fas fa-heading",
        "core.LandingPageReview": "fas fa-star",
        "core.LegalPage": "fas fa-scale-balanced",
        "core.MasterAvailability": "fas fa-business-time",
        "core.MasterProfile": "fas fa-user-tie",
        "core.MasterRoom": "fas fa-warehouse",
        "core.Notification": "fas fa-bell",
        "core.PageView": "fas fa-chart-area",
        "core.Payment": "fas fa-sack-dollar",
        "core.PaymentMethod": "fas fa-credit-card",
        "core.PaymentStatus": "fas fa-list-check",
        "core.PrepaymentOption": "fas fa-piggy-bank",
        "core.PromoCode": "fas fa-ticket-alt",
        "core.ProjectJournalEntry": "fas fa-newspaper",
        "core.Role": "fas fa-shield-halved",
        "core.Service": "fas fa-screwdriver-wrench",
        "core.ServiceCategory": "fas fa-diagram-project",
        "core.ServiceDiscount": "fas fa-badge-percent",
        "core.ServiceMaster": "fas fa-user-gear",
        "core.UserProfile": "fas fa-id-badge",
        "core.UserRole": "fas fa-user-tag",
        "core.VisitorSession": "fas fa-user-clock",
        "store.CarMake": "fas fa-industry",
        "store.CarModel": "fas fa-car-side",
        "store.Category": "fas fa-tags",
        "store.CustomFitmentRequest": "fas fa-ruler-combined",
        "store.Order": "fas fa-cart-shopping",
        "store.OrderItem": "fas fa-receipt",
        "store.Product": "fas fa-box-open",
        "store.ProductImage": "fas fa-images",
        "store.ProductOption": "fas fa-sliders-h",
        "notifications.TelegramBotSettings": "fas fa-robot",
        "notifications.TelegramReminder": "fas fa-stopwatch",
        "notifications.TelegramMessageLog": "fas fa-envelope-open-text",
        "notifications.TelegramContact": "fas fa-address-book",
    },
    "custom_sidebar": ADMIN_SIDEBAR_SECTIONS,
    "theme": "None",
    #  "custom_css": "static/admin/css/custom_sidebar.css",
}
JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": False,
    "accent": "accent-primary",
    "navbar": "navbar-white navbar-light",
    "no_navbar_border": False,
    "navbar_fixed": False,
    "layout_boxed": False,
    "footer_fixed": False,
    "sidebar_fixed": False,
    "sidebar": "sidebar-dark-primary",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": False,
    "sidebar_nav_compact_style": False,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": False,


    "button_classes": {
        "primary": "btn-outline-primary",
        "secondary": "btn-outline-secondary",
        "info": "btn-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success",
    },
    
}


# ── Аутентификация ───────────────────────────────────────────────────────
LOGIN_URL = "login"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "core.auth_backends.EmailPhoneBackend",
]
LOGIN_REDIRECT_URL = "/home/"
LOGOUT_REDIRECT_URL = "/home/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Логи в stdout (dokku logs) ───────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
}



STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
# карта sourcemap .css.map по-прежнему может отсутствовать — это ок:
WHITENOISE_IGNORE_MISSING_FILES = True
