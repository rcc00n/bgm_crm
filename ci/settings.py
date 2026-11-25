"""Synthetic, network-disabled settings for focused CI only.

These settings are opt-in through ci/checks.py; application entry points are not
changed. Forced local values prevent an ambient production environment from being
used by an accidental invocation of the checks.
"""
import os
from pathlib import Path

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['SECRET_KEY'] = 'SYNTHETIC-CI-ONLY-DO-NOT-USE-FOR-A-DEPLOYMENT-2026'
os.environ['DJANGO_SECRET_KEY'] = 'SYNTHETIC-CI-ONLY-DO-NOT-USE-FOR-A-DEPLOYMENT-2026'
os.environ['DEBUG'] = 'True'
os.environ['DJANGO_DEBUG'] = 'True'
os.environ['ALLOWED_HOSTS'] = 'localhost,127.0.0.1,testserver'
os.environ['DJANGO_ALLOWED_HOSTS'] = 'localhost,127.0.0.1,testserver'
os.environ['EMAIL_BACKEND'] = 'django.core.mail.backends.locmem.EmailBackend'
os.environ['DEFAULT_FROM_EMAIL'] = 'ci@example.invalid'
os.environ['SERVER_EMAIL'] = 'ci@example.invalid'
os.environ['SENDGRID_API_KEY'] = ''
os.environ['USE_SENDGRID'] = 'False'
os.environ['USE_TWILIO'] = 'False'
os.environ['TWILIO_ACCOUNT_SID'] = ''
os.environ['TWILIO_AUTH_TOKEN'] = ''
os.environ['TWILIO_FROM_NUMBER'] = ''
os.environ['TELEGRAM_BOT_TOKEN'] = ''
os.environ['TELEGRAM_NOTIFICATIONS_ENABLED'] = 'False'
os.environ['TELEGRAM_AI_ENABLED'] = 'False'
os.environ['TELEGRAM_ADMIN_PASSPHRASE'] = ''
os.environ['OPENAI_API_KEY'] = ''
os.environ['CELERY_BROKER_URL'] = 'memory://'
os.environ['CELERY_RESULT_BACKEND'] = 'cache+memory://'
os.environ['REDIS_URL'] = 'memory://'
os.environ['LEAD_REDIS_URL'] = ''
os.environ['USE_S3'] = 'False'
os.environ['USE_S3_MEDIA'] = 'False'
os.environ['AWS_STORAGE_BUCKET_NAME'] = ''
os.environ['AWS_ACCESS_KEY_ID'] = ''
os.environ['AWS_SECRET_ACCESS_KEY'] = ''
os.environ['AWS_S3_SIGNATURE_NAME'] = 's3v4'
os.environ['AWS_S3_REGION_NAME'] = 'us-east-1'
os.environ['AWS_S3_FILE_OVERWRITE'] = 'False'
os.environ['AWS_DEFAULT_ACL'] = ''
os.environ['AWS_QUERYSTRING_AUTH'] = 'False'
os.environ['STRIPE_SECRET_KEY'] = ''
os.environ['STRIPE_PUBLIC_KEY'] = ''
os.environ['STRIPE_PUBLISHABLE_KEY'] = ''
os.environ['STRIPE_WEBHOOK_SECRET'] = ''
os.environ['SQUARE_ACCESS_TOKEN'] = ''
os.environ['SQUARE_APPLICATION_ID'] = ''
os.environ['SQUARE_LOCATION_ID'] = ''
os.environ['PRINTFUL_TOKEN'] = ''
os.environ['PRINTFUL_WEBHOOK_SECRET'] = ''
os.environ['OCR_STORE_UPLOADS'] = 'False'
os.environ['OCR_DEBUG'] = 'False'

from booking.settings import *  # noqa: E402,F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
SECRET_KEY = "SYNTHETIC-CI-ONLY-DO-NOT-USE-FOR-A-DEPLOYMENT-2026"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = False
USE_S3 = False
USE_S3_MEDIA = False
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
LOGGING = {"version": 1, "disable_existing_loggers": False, "handlers": {"console": {"class": "logging.StreamHandler"}}, "root": {"handlers": ["console"], "level": "WARNING"}}

ROOT_URLCONF = "ci.urls"
