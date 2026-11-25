"""Opt-in PostgreSQL regression settings; never use for a deployed application."""
from .settings import *  # noqa: F401,F403
import os

if os.environ.get("REVIEW_POSTGRES") != "1":
    raise RuntimeError("Use an isolated PostgreSQL instance and set REVIEW_POSTGRES=1")

# A production DATABASE_URL is deliberately ignored. Only the synthetic local
# service named in ci/README.md can be selected; no arbitrary remote host is accepted.
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "HOST": "127.0.0.1",
    "PORT": int(os.environ.get("REVIEW_POSTGRES_PORT", "5432")),
    "NAME": "review",
    "USER": "ci_review",
    "PASSWORD": "synthetic-local-only",
    "TEST": {"NAME": "test_review_bgm_crm"},
    "CONN_MAX_AGE": 0,
}}
ROOT_URLCONF = "booking.urls"
