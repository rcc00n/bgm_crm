"""Existing business regressions against a disposable PostgreSQL service.

External socket connections are blocked before Django imports. Provider calls in
selected tests must be mocked; the sole allowed network destination is local PG.
"""
from pathlib import Path
import os
import socket
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ["DJANGO_SETTINGS_MODULE"] = "ci.postgres_settings"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
if os.environ.get("REVIEW_POSTGRES") != "1":
    raise RuntimeError("Set REVIEW_POSTGRES=1 only for the isolated CI PostgreSQL service")
port = int(os.environ.get("REVIEW_POSTGRES_PORT", "5432"))
connect = socket.socket.connect
connect_ex = socket.socket.connect_ex
getaddrinfo = socket.getaddrinfo

def check_address(address):
    if not isinstance(address, tuple) or address[0] not in ("localhost", "127.0.0.1", "::1") or int(address[1]) != port:
        raise RuntimeError("External networking is disabled in business regression checks")

def guarded_connect(sock, address):
    check_address(address)
    return connect(sock, address)

def guarded_connect_ex(sock, address):
    check_address(address)
    return connect_ex(sock, address)

def guarded_resolve(host, service, *args, **kwargs):
    check_address((host, service))
    return getaddrinfo(host, service, *args, **kwargs)

socket.socket.connect = guarded_connect
socket.socket.connect_ex = guarded_connect_ex
socket.getaddrinfo = guarded_resolve

import django  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.test import override_settings  # noqa: E402

django.setup()
with tempfile.TemporaryDirectory(prefix="business-ci-media-") as media:
    with override_settings(MEDIA_ROOT=media):
        call_command("check")
        call_command("test", *['core.tests.test_booking_api', 'store.tests.test_checkout_payment_mode', 'store.tests.test_checkout_reference_files', 'store.tests.test_inventory_controls', 'core.tests.test_printful_checkout_api', 'notifications.test_delivery', 'notifications.test_delivery_concurrency'], verbosity=2, interactive=False)
