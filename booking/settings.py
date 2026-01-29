from pathlib import Path
from decimal import Decimal, InvalidOperation
import os
import dj_database_url
from decouple import config, Csv  

BASE_DIR = Path(__file__).resolve().parent.parent


def _dec_env(name: str, default: str) -> Decimal:
    """
    Safe Decimal parser for numeric env vars.
    """
    try:
        return Decimal(os.getenv(name, default))
    except (InvalidOperation, TypeError):
        return Decimal(default)


def _bool_env(name: str, default: str = "False") -> bool:
    """
    Safe boolean parser for env vars.
    Accepts: 1/0, true/false, yes/no, on/off (case-insensitive).
    """
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "y", "on"}

# ── Основное ─────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
DEBUG = _bool_env("DEBUG", "False")

ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("ALLOWED_HOSTS", "*").split(",")
    if h.strip()
]

# ── Бренд и маркетинг ───────────────────────────────────────────────────
SITE_BRAND_NAME = os.getenv(
    "SITE_BRAND_NAME",
    "BGM Customs",
)
SITE_BRAND_TAGLINE = os.getenv(
    "SITE_BRAND_TAGLINE",
    "Performance builds and outlaw styling out of Calgary.",
)
SITE_DEFAULT_DESCRIPTION = os.getenv(
    "SITE_DEFAULT_DESCRIPTION",
    "BGM Customs delivers bespoke performance builds, detailing and premium parts sourcing for enthusiasts across North America.",
)
SITE_DEFAULT_KEYWORDS = os.getenv(
    "SITE_DEFAULT_KEYWORDS",
    ", ".join([
        "custom fabrication shop",
        "custom truck fabrication",
        "custom diesel shop",
        "diesel performance shop",
        "truck performance upgrades",
        "custom bumpers Alberta",
        "custom running boards Alberta",
        "custom flat deck builders",
        "custom welding shop Medicine Hat",
        "CNC plasma cutting Medicine Hat",
        "Armadillo bedliner",
        "Smooth Criminal Liner",
        "spray-in bedliner Medicine Hat",
        "custom fabrication Medicine Hat",
        "diesel performance Medicine Hat",
        "truck accessories Medicine Hat",
        "welders Medicine Hat",
        "truck lift kits Medicine Hat",
        "heavy-duty truck upgrades Alberta",
        "custom truck builders Alberta",
        "custom steel bumpers",
        "steel fender flares Canada",
        "14 gauge steel fender flares",
        "off-road truck bumpers Canada",
        "plasma-cut truck parts",
        "custom mudflaps Canada",
        "truck bedliner coating",
        "Armadillo liner dealer",
        "SCL bedliner coating",
        "custom 4-link suspension",
        "body swap services Alberta",
        "Outlaw Series bumpers",
        "Badland Bars rock sliders",
        "custom headache racks",
        "custom fender flare kits",
        "steel running boards Canada",
        "flat deck fabrication Alberta",
        "truck armor coating",
        "diesel enthusiasts Alberta",
        "truck customization Alberta",
        "off-road truck upgrades Canada",
        "SEMA-style builds Canada",
        "truck builders Canada",
        "best custom truck fabrication shop in Medicine Hat",
        "where to get custom diesel performance upgrades in Alberta",
        "custom plasma-cut truck parts Canada",
        "strong steel bumpers for heavy-duty trucks",
        "best spray-in bedliner for work trucks",
        "custom truck builders for lifted trucks",
        "who builds custom flat decks in Alberta",
        "steel fender flares for Dodge/Ram/Chevy/Ford trucks",
        "Bad Guy Motors",
        "Bad Guy Motors Medicine Hat",
        "BGM custom fabrication",
        "BGM truck accessories",
        "BGM steel bumpers",
        "BGM Armadillo liner",
        "BGM Smooth Criminal Liner",
        "diesel performance upgrades",
        "diesel tuning shop",
        "truck tuning Medicine Hat",
        "ECM tuning Alberta",
        "diesel delete services",
        "turbo upgrades Alberta",
        "performance truck shop",
        "truck horsepower upgrades",
        "custom performance fabrication",
        "heavy-duty performance upgrades",
        "custom diesel tuning Canada",
        "ECM tuning Medicine Hat",
        "HP Tuners Alberta",
        "MPVI4 dealer Alberta",
        "remote tuning Canada",
        "performance calibration shop",
        "diesel engine upgrades",
        "custom turbo install Alberta",
        "upgraded intercooler install",
        "high-flow exhaust install",
        "EGR delete kits Canada",
        "head studs installation Alberta",
        "cold air intake install shop",
        "performance injector upgrades",
        "custom lift kits Alberta",
        "4-link suspension kits",
        "coilover suspension upgrades",
        "off-road suspension upgrades",
        "performance suspension fabrication",
        "custom shock tuning",
        "Cummins performance shop Alberta",
        "Powerstroke performance Alberta",
        "Duramax performance upgrades",
        "6.7 Powerstroke tuning",
        "5.9 Cummins upgrades",
        "6.6 Duramax tuning",
        "Ram diesel tuning Alberta",
        "Ford diesel performance shop",
        "best diesel performance shop in Medicine Hat",
        "where to get diesel tuning done in Alberta",
        "affordable ECM tuning for diesel trucks",
        "custom turbo install shop near me",
        "diesel horsepower upgrade services",
        "who installs head studs in Alberta",
        "best performance shop for lifted trucks",
        "diesel tuning without a dyno",
        "custom suspension for SEMA builds",
        "performance upgrades Medicine Hat",
        "diesel tuning Medicine Hat",
        "turbo install Medicine Hat",
        "diesel mechanic Medicine Hat",
        "performance truck shop Alberta",
        "vehicle inspections Medicine Hat",
        "out of province inspections Medicine Hat",
        "salvage inspections Alberta",
        "commercial vehicle inspections Alberta",
        "truck inspection shop Medicine Hat",
        "AMVIC inspection services",
        "safety inspections for diesel trucks",
        "diesel truck repairs Alberta",
        "truck servicing Medicine Hat",
        "heavy-duty truck repairs",
        "performance truck maintenance",
        "diesel engine diagnostics",
        "exhaust repair Medicine Hat",
        "coolant system repairs",
        "fuel system repairs diesel",
        "brake repair Medicine Hat",
        "truck brake service Alberta",
        "suspension repair shop",
        "control arm replacements",
        "bushing replacements",
        "performance brake upgrades",
        "wheel and tire shop Medicine Hat",
        "truck tires Alberta",
        "tire mounting and balancing",
        "wheel alignment Medicine Hat",
        "all-terrain tire sales Alberta",
        "winter tires Medicine Hat",
        "truck rim repair and replacement",
        "differential service Medicine Hat",
        "transmission service diesel trucks",
        "fluid changes for heavy-duty trucks",
        "steering system repairs",
        "wheel bearing replacement",
        "truck maintenance packages",
        "work truck repair shop Alberta",
    ]),
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
    "default_keywords": SITE_DEFAULT_KEYWORDS,
    "google_tag_manager_id": os.getenv("GOOGLE_TAG_MANAGER_ID", "GTM-M7FTNXV6"),
    "google_ads_id": os.getenv("GOOGLE_ADS_ID", ""),
    "google_ads_conversion_label": os.getenv("GOOGLE_ADS_CONVERSION_LABEL", ""),
    "google_ads_send_page_view": _bool_env("GOOGLE_ADS_SEND_PAGE_VIEW", "True"),
}

# ── Company contact (email footer defaults) ──────────────────────────────
COMPANY_ADDRESS = os.getenv(
    "COMPANY_ADDRESS",
    "620 Porcelain Ave SE, Medicine Hat, AB T1A 0C2",
)
COMPANY_PHONE = os.getenv("COMPANY_PHONE", "(403) 525-0432")
COMPANY_WEBSITE = os.getenv("COMPANY_WEBSITE", "badguymotors.com")
EMAIL_ACCENT_COLOR = os.getenv("EMAIL_ACCENT_COLOR", "#d50000")
EMAIL_DARK_COLOR = os.getenv("EMAIL_DARK_COLOR", "#0b0b0c")
EMAIL_BG_COLOR = os.getenv("EMAIL_BG_COLOR", "#0b0b0c")
SITE_NOTICE_PROMO_CODE = os.getenv("SITE_NOTICE_PROMO_CODE", "")
SITE_NOTICE_BEST_SELLERS_URL = os.getenv("SITE_NOTICE_BEST_SELLERS_URL", "")
SITE_NOTICE_SERVICES_URL = os.getenv("SITE_NOTICE_SERVICES_URL", "")
SITE_NOTICE_BOOKING_URL = os.getenv("SITE_NOTICE_BOOKING_URL", "")
ABANDONED_CART_EMAIL_1_DELAY_HOURS = int(os.getenv("ABANDONED_CART_EMAIL_1_DELAY_HOURS", "2"))
ABANDONED_CART_EMAIL_2_DELAY_HOURS = int(os.getenv("ABANDONED_CART_EMAIL_2_DELAY_HOURS", "24"))
ABANDONED_CART_EMAIL_3_DELAY_HOURS = int(os.getenv("ABANDONED_CART_EMAIL_3_DELAY_HOURS", "72"))
ABANDONED_CART_CART_URL = os.getenv("ABANDONED_CART_CART_URL", "")
ABANDONED_CART_CHECKOUT_URL = os.getenv("ABANDONED_CART_CHECKOUT_URL", "")
ABANDONED_CART_STORE_URL = os.getenv("ABANDONED_CART_STORE_URL", "")
ORDER_REVIEW_REQUEST_DELAY_DAYS = int(os.getenv("ORDER_REVIEW_REQUEST_DELAY_DAYS", "5"))
ORDER_REVIEW_URL = os.getenv("ORDER_REVIEW_URL", "")

# ── Currency ──────────────────────────────────────────────────────────────
DEFAULT_CURRENCY_CODE = os.getenv("DEFAULT_CURRENCY_CODE", "CAD")
DEFAULT_CURRENCY_SYMBOL = os.getenv("DEFAULT_CURRENCY_SYMBOL", "$")

# ── Payments (Square / Interac) ──────────────────────────────────────────
SQUARE_ACCESS_TOKEN = os.getenv("SQUARE_ACCESS_TOKEN", "")
SQUARE_LOCATION_ID = os.getenv("SQUARE_LOCATION_ID", "")
SQUARE_APPLICATION_ID = os.getenv("SQUARE_APPLICATION_ID", "")
SQUARE_ENVIRONMENT = os.getenv("SQUARE_ENVIRONMENT", "production").lower()
SQUARE_FEE_PERCENT = _dec_env("SQUARE_FEE_PERCENT", "0.029")  # 2.9% default
SQUARE_FEE_FIXED = _dec_env("SQUARE_FEE_FIXED", "0.30")      # $0.30 default
STORE_GST_RATE = _dec_env("STORE_GST_RATE", "0.05")          # 5% GST
STORE_PROCESSING_FEE_RATE = _dec_env("STORE_PROCESSING_FEE_RATE", "0.035")  # 3.5% processing fee
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "openaicamrose@gmail.com")
ETRANSFER_EMAIL = os.getenv("ETRANSFER_EMAIL", SUPPORT_EMAIL or "Payments@badguymotors.ca")
ETRANSFER_MEMO_HINT = os.getenv(
    "ETRANSFER_MEMO_HINT",
    "Include your order number and phone in the transfer message.",
)

# ── Email (SendGrid SMTP) ────────────────────────────────────────────────
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.sendgrid.net")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "apikey")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", os.getenv("SENDGRID_API_KEY", ""))
EMAIL_USE_SSL = _bool_env("EMAIL_USE_SSL", "False")
EMAIL_USE_TLS = _bool_env("EMAIL_USE_TLS", "True")
if EMAIL_USE_SSL:
    EMAIL_USE_TLS = False
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", SUPPORT_EMAIL or "")
EMAIL_VERIFICATION_RESEND_MINUTES = int(os.getenv("EMAIL_VERIFICATION_RESEND_MINUTES", "10"))

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
    "core.middleware.AuthIdleTimeoutMiddleware",
    "core.middleware.AdminSidebarSeenMiddleware",
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
                "core.context_processors_core.topbar_style",
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
SECURE_SSL_REDIRECT = _bool_env("SECURE_SSL_REDIRECT", "True")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h]

# ── Сессии ──────────────────────────────────────────────────────────────
# Принудительный логаут после 30 минут бездействия.
SESSION_COOKIE_AGE = 60 * 30
SESSION_SAVE_EVERY_REQUEST = False
AUTH_IDLE_TIMEOUT_SECONDS = 60 * 30

# ── Jazzmin (как было) ───────────────────────────────────────────────────
ADMIN_SIDEBAR_SECTIONS = [
    {
        "label": "Operations",
        "icon": "fas fa-tachometer-alt",
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
                "icon": "fas fa-user-cog",
                "items": [
                    {"model": "core.MasterAvailability", "label": "Availability"},
                    {"model": "core.MasterProfile", "label": "Team Profiles"},
                    {"model": "core.ServiceMaster", "label": "Service Assignment"},
                    {"model": "core.MasterRoom", "label": "Rooms & Bays"},
                ],
            },
            {
                "label": "Payments",
                "icon": "fas fa-money-bill-wave",
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
            {
                "label": "Automation",
                "icon": "fas fa-robot",
                "items": [
                    {"model": "notifications.TelegramContact", "label": "Contacts"},
                    {"model": "notifications.TelegramBotSettings", "label": "Bot Settings"},
                    {"model": "notifications.TelegramReminder", "label": "Reminders"},
                    {"model": "notifications.TelegramMessageLog", "label": "Delivery Log"},
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
                "label": "Inbound Leads",
                "icon": "fas fa-inbox",
                "items": [
                    {"model": "core.ServiceLead", "label": "Service Leads"},
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
                    {"model": "store.StorePricingSettings", "label": "Pricing Settings"},
                    {"model": "store.Category", "label": "Product Categories"},
                    {"model": "store.Product"},
                    {"model": "store.ProductImage", "label": "Product Gallery"},
                    {"model": "store.ProductOption", "label": "Product Options"},
                ],
            },
            {
                "label": "Services Catalog",
                "icon": "fas fa-tools",
                "items": [
                    {"model": "core.ServiceCategory", "label": "Service Categories"},
                    {"model": "core.Service"},
                ],
            },
            {
                "label": "Vehicles & Fitment",
                "icon": "fas fa-car-side",
                "items": [
                    {"model": "store.CarMake", "label": "Car Makes"},
                    {"model": "store.CarModel", "label": "Car Models"},
                    {
                        "model": "store.CustomFitmentRequest",
                        "label": "Fitment Requests",
                        "activity_field": "created_at",
                    },
                ],
            },
            {
                "label": "Orders",
                "icon": "fas fa-shopping-cart",
                "items": [
                    {"model": "store.Order", "label": "Orders"},
                    {"model": "store.OrderItem", "label": "Order Items"},
                ],
            },
        ],
    },
    {
        "label": "Website Content",
        "icon": "fas fa-globe",
        "groups": [
            {
                "label": "Branding & Fonts",
                "icon": "fas fa-font",
                "items": [
                    {"model": "core.FontPreset", "label": "Font Library"},
                    {"model": "core.PageFontSetting", "label": "Page Fonts"},
                    {"model": "core.AdminLoginBranding", "label": "Admin Login Branding"},
                ],
            },
            {
                "label": "Media & Hero Assets",
                "icon": "fas fa-images",
                "items": [
                    {"model": "core.HeroImage", "label": "Hero Assets"},
                ],
            },
            {
                "label": "Page Copy",
                "icon": "fas fa-pen-nib",
                "items": [
                    {"model": "core.HomePageCopy", "label": "Home Page Copy"},
                    {"model": "core.ServicesPageCopy", "label": "Services Page Copy"},
                    {"model": "core.StorePageCopy", "label": "Products Page Copy"},
                    {"model": "core.FinancingPageCopy", "label": "Financing Page Copy"},
                    {"model": "core.AboutPageCopy", "label": "About Page Copy"},
                    {"model": "core.DealerStatusPageCopy", "label": "Dealer Portal Copy"},
                    {"model": "core.ClientPortalPageCopy", "label": "Client Portal Copy"},
                    {"model": "core.MerchPageCopy", "label": "Merch Page Copy"},
                    {"model": "core.LegalPage", "label": "Legal Pages"},
                    {"model": "core.LandingPageReview", "label": "Landing Reviews"},
                    {"model": "core.ProjectJournalEntry", "label": "Project Journal"},
                ],
            },
            {
                "label": "Messaging",
                "icon": "fas fa-bell",
                "items": [
                    {"model": "core.Notification", "label": "Notifications"},
                    {
                        "model": "core.EmailCampaign",
                        "label": "Email Campaigns",
                        "activity_field": "created_at",
                    },
                    {
                        "model": "core.EmailSubscriber",
                        "label": "Email Subscribers",
                        "activity_field": "created_at",
                    },
                    {"model": "core.EmailTemplate", "label": "Email Templates"},
                ],
            },
        ],
    },
    {
        "label": "System",
        "icon": "fas fa-shield-alt",
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
        "core.AppointmentStatus": "fas fa-dot-circle",
        "core.AppointmentStatusHistory": "fas fa-wave-square",
        "core.AppointmentPrepayment": "fas fa-coins",
        "core.AppointmentPromoCode": "fas fa-ticket-alt",
        "core.ClientFile": "fas fa-folder-open",
        "core.ClientReview": "fas fa-comments",
        "core.ClientSource": "fas fa-bullseye",
        "core.DealerApplication": "fas fa-user-check",
        "core.DealerTierLevel": "fas fa-medal",
        "core.HeroImage": "fas fa-image",
        "core.HomePageCopy": "fas fa-pen-nib",
        "core.FinancingPageCopy": "fas fa-credit-card",
        "core.AboutPageCopy": "fas fa-info-circle",
        "core.DealerStatusPageCopy": "fas fa-handshake",
        "core.ClientPortalPageCopy": "fas fa-id-card",
        "core.MerchPageCopy": "fas fa-tshirt",
        "core.ServicesPageCopy": "fas fa-clipboard-list",
        "core.StorePageCopy": "fas fa-store",
        "core.FontPreset": "fas fa-font",
        "core.PageFontSetting": "fas fa-heading",
        "core.AdminLoginBranding": "fas fa-sign-in-alt",
        "core.EmailTemplate": "fas fa-envelope-open-text",
        "core.EmailCampaign": "fas fa-paper-plane",
        "core.EmailSubscriber": "fas fa-user-plus",
        "core.EmailCampaignRecipient": "fas fa-envelope",
        "core.LandingPageReview": "fas fa-star",
        "core.LegalPage": "fas fa-balance-scale",
        "core.MasterAvailability": "fas fa-business-time",
        "core.MasterProfile": "fas fa-user-tie",
        "core.MasterRoom": "fas fa-warehouse",
        "core.Notification": "fas fa-bell",
        "core.PageView": "fas fa-chart-area",
        "core.Payment": "fas fa-money-bill-wave",
        "core.PaymentMethod": "fas fa-credit-card",
        "core.PaymentStatus": "fas fa-clipboard-check",
        "core.PrepaymentOption": "fas fa-piggy-bank",
        "core.PromoCode": "fas fa-ticket-alt",
        "core.ProjectJournalEntry": "fas fa-newspaper",
        "core.Role": "fas fa-user-shield",
        "core.Service": "fas fa-tools",
        "core.ServiceCategory": "fas fa-project-diagram",
        "core.ServiceDiscount": "fas fa-percent",
        "core.ServiceLead": "fas fa-inbox",
        "core.ServiceMaster": "fas fa-user-cog",
        "core.UserProfile": "fas fa-id-badge",
        "core.UserRole": "fas fa-user-tag",
        "core.VisitorSession": "fas fa-user-clock",
        "store.CarMake": "fas fa-industry",
        "store.CarModel": "fas fa-car-side",
        "store.Category": "fas fa-tags",
        "store.CustomFitmentRequest": "fas fa-ruler-combined",
        "store.Order": "fas fa-shopping-cart",
        "store.OrderItem": "fas fa-receipt",
        "store.StorePricingSettings": "fas fa-percent",
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
    "core.auth_backends.EmailPhoneBackend",
]
LOGIN_REDIRECT_URL = "/home/"
LOGOUT_REDIRECT_URL = "home"
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
