"""Isolated SYNTHETIC showcase settings. Production settings/.env are never imported."""

from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parents[2]
STATE_DIR = Path(os.environ["SHOWCASE_STATE_DIR"]).resolve()
if not STATE_DIR.is_dir() or not (STATE_DIR / ".synthetic-showcase").is_file():
    raise RuntimeError("Use a newly prepared synthetic showcase state directory")
SECRET_KEY = (STATE_DIR / "django-secret").read_text().strip()
DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
CSRF_TRUSTED_ORIGINS = ["http://127.0.0.1:" + os.environ.get("SHOWCASE_PORT", "3387")]
INSTALLED_APPS = [
    "phonenumbers",
    "accounts",
    "core.apps.CoreConfig",
    "notifications",
    "ckeditor",
    "ckeditor_uploader",
    "dal",
    "dal_select2",
    "jazzmin",
    "sorl.thumbnail",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "store",
]
MIDDLEWARE = [
    "showcase_middleware.SyntheticDemoMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "booking.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "booking/templates", BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": STATE_DIR / "demo.sqlite3",
    }
}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.PBKDF2PasswordHasher"]
AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "ru"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = STATE_DIR / "static"
MEDIA_URL = "/media/"
MEDIA_ROOT = STATE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DEFAULT_FROM_EMAIL = "showcase@example.invalid"
LOGIN_REDIRECT_URL = "rentals:dashboard"
LOGOUT_REDIRECT_URL = "login"
LOGIN_URL = "login"
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Only this newly initialized private demo PostgreSQL namespace may be used.
import json

PG = json.loads((STATE_DIR / "postgres.json").read_text())
if PG["host"] != "127.0.0.1" or PG["database"] != "bgm_showcase":
    raise RuntimeError("Refusing a non-showcase database")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": PG["database"],
        "USER": PG["user"],
        "PASSWORD": Path(PG["password_file"]).read_text().strip(),
        "HOST": PG["host"],
        "PORT": PG["port"],
        "CONN_MAX_AGE": 0,
    }
}
LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Edmonton"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "client-dashboard"
LOGOUT_REDIRECT_URL = "home"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_FROM_EMAIL = "showcase@example.invalid"
SERVER_EMAIL = "showcase@example.invalid"
EMAIL_HOST = ""
EMAIL_HOST_USER = ""
EMAIL_HOST_PASSWORD = ""
EMAIL_USE_TLS = False
AWS_ACCESS_KEY_ID = ""
AWS_SECRET_ACCESS_KEY = ""
AWS_STORAGE_BUCKET_NAME = ""
AWS_S3_REGION_NAME = ""
USE_S3_MEDIA = False
SQUARE_ACCESS_TOKEN = ""
SQUARE_APPLICATION_ID = ""
SQUARE_LOCATION_ID = ""
SQUARE_ENVIRONMENT = "sandbox"
PRINTFUL_TOKEN = ""
TELEGRAM_BOT_TOKEN = ""
IP_GEOLOCATION_ENABLED = False
LEAD_REDIS_URL = ""
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "synthetic-bgm-showcase",
    }
}
TEMPLATES[0]["OPTIONS"]["context_processors"] += [
    "core.context_processors_core.hero_media",
    "core.context_processors_core.dealer_portal",
    "core.context_processors_core.currency",
    "core.context_processors_core.store_shipping",
    "core.context_processors_core.marketing_tags",
    "core.context_processors_core.company_info",
    "core.context_processors_core.site_contact",
    "core.context_processors_core.topbar_style",
    "core.context_processors_core.cart_summary",
]
CKEDITOR_UPLOAD_PATH = "showcase-uploads/"
CKEDITOR_CONFIGS = {"default": {"toolbar": "Basic"}}
CKEDITOR_ALLOW_NONIMAGE_FILES = False
CKEDITOR_RESTRICT_BY_USER = True
CKEDITOR_BASEPATH = "/static/ckeditor/ckeditor/"
DEFAULT_CURRENCY_CODE = "CAD"
DEFAULT_CURRENCY_SYMBOL = "$"
DEFAULT_COUNTRY_CODE = "CA"
COMPANY_NAME = "SYNTHETIC Demo Automotive"
COMPANY_EMAIL = "showcase@example.invalid"
COMPANY_PHONE = "+12025550123"
COMPANY_ADDRESS = "SYNTHETIC LOCAL DEMO — NO REAL LOCATION"

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
CKEDITOR_CONFIGS["pagecopy"] = {"toolbar": "Basic", "allowedContent": True}
JAZZMIN_SETTINGS = {
    "site_title": "BGM CRM — SYNTHETIC DEMO",
    "site_header": "BGM CRM",
    "site_brand": "BGM CRM",
    "welcome_sign": "Synthetic local demonstration",
}
