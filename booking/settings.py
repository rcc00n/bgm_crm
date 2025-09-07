from pathlib import Path
import os
import dj_database_url
from decouple import config, Csv  # оставил, если используешь .env локально

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Основное ─────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
DEBUG = os.getenv("DEBUG", "False") == "True"

ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "*").split(",") if h.strip()]

# ── Приложения ───────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "phonenumbers",
    "accounts",
    "core",
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
            ],
        },
    },
]

WSGI_APPLICATION = "booking.wsgi.application"

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
TIME_ZONE = "Canada/Mountain"
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
JAZZMIN_SETTINGS = {
    "site_title": "Malva Admin",
    "site_header": "Malva Health & Beauty",
    "welcome_sign": "Welcome to Malva",
    "copyright": "Malva © 2025",
    "search_model": ["auth.User"],
    "show_sidebar": True,
    "navigation_expanded": True,
    "show_ui_builder": False,
    "hide_models": ["Groups"],
    "topmenu_links": [{"name": "Webpage", "url": "/", "permissions": ["auth.view_user"]}],
    "icons": {
        "auth.User": "fas fa-user",
        "auth.Group": "fas fa-users-cog",
        "core.Appointment": "fas fa-calendar-check",
        "core.AppointmentStatus": "fas fa-info-circle",
        "core.AppointmentStatusHistory": "fas fa-history",
        "core.AppointmentPrepayment": "fas fa-coins",
        "core.ClientFile": "fas fa-file-alt",
        "core.Notification": "fas fa-bell",
        "core.Payment": "fas fa-money-check-alt",
        "core.PaymentMethod": "fas fa-credit-card",
        "core.PaymentStatus": "fas fa-receipt",
        "core.PrepaymentOption": "fas fa-percentage",
        "core.Role": "fas fa-user-tag",
        "core.UserRole": "fas fa-user-friends",
        "core.Service": "fas fa-spa",
        "core.ServiceMaster": "fas fa-user-cog",
    },
    "menu": [
        {"label": "📅 Appointments", "models": ["core.appointment", "core.appointmentstatus", "core.appointmentprepayment", "core.appointmentstatushistory"]},
        {"label": "🧑‍💼 Users", "models": ["core.user", "core.userprofile", "core.role", "core.userrole", "core.clientfile"]},
        {"label": "💳 Payments", "models": ["core.payment", "core.paymentstatus", "core.paymentmethod"]},
        {"label": "🛎️ Services", "models": ["core.service", "core.servicemaster"]},
        {"label": "🔔 Notifications", "models": ["core.notification"]},
        {"label": "👨‍🏫 Masters", "models": ["core.masterprofile", "core.masteravailability"]},
    ],
    "theme": "None",
    # "custom_css": "admin/css/custom_sidebar.css"
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
    "sidebar_fixed": True,
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
