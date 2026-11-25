"""SYNTHETIC isolated BGM records; no production settings or provider configuration."""

import os, json
from pathlib import Path
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

os.environ["DJANGO_SETTINGS_MODULE"] = "showcase_settings"
import django

django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from core.models import (
    Role,
    UserRole,
    ServiceCategory,
    Service,
    MasterProfile,
    ServiceMaster,
    PaymentStatus,
    Appointment,
    AppointmentStatus,
    AppointmentStatusHistory,
    SiteContactSettings,
)
from store.models import Category, Product

state = Path(os.environ["SHOWCASE_STATE_DIR"])
if Appointment.objects.exists():
    raise RuntimeError("Refusing to seed existing showcase appointment data")
User = get_user_model()
pwd = (state / "admin-password").read_text().strip()
admin = User.objects.create_superuser(
    "synthetic-demo",
    "operator@example.invalid",
    pwd,
    first_name="SYNTHETIC",
    last_name="Operator",
)
tech = User.objects.create_user(
    "synthetic-tech",
    "tech@example.invalid",
    pwd,
    first_name="SYNTHETIC",
    last_name="Technician",
)
client = User.objects.create_user(
    "synthetic-client",
    "customer@example.invalid",
    pwd,
    first_name="SYNTHETIC",
    last_name="Customer",
)
for role_name, user in [("Admin", admin), ("Master", tech), ("Client", client)]:
    role, _ = Role.objects.get_or_create(name=role_name)
    UserRole.objects.get_or_create(user=user, role=role)
profile, _ = MasterProfile.objects.get_or_create(user=tech)
profile.profession = "SYNTHETIC automotive technician"
profile.work_start = time(8)
profile.work_end = time(18)
profile.save()
category = ServiceCategory.objects.create(name="SYNTHETIC Vehicle Care")
services = []
for title, price, minutes in [
    ("SYNTHETIC Wheel Alignment", "129.00", 60),
    ("SYNTHETIC Brake Inspection", "79.00", 45),
    ("SYNTHETIC Seasonal Tire Service", "99.00", 60),
]:
    item = Service.objects.create(
        name=title,
        category=category,
        description="SYNTHETIC demonstration service; no real booking or charge.",
        base_price=Decimal(price),
        duration_min=minutes,
    )
    services.append(item)
    ServiceMaster.objects.create(service=item, master=tech)
assert services[0].base_price_amount() == Decimal("129.00")
pending, _ = PaymentStatus.objects.get_or_create(name="Pending")
confirmed, _ = AppointmentStatus.objects.get_or_create(name="Confirmed")
appointments = []
for i, service in enumerate(services):
    a = Appointment(
        client=client,
        master=tech,
        service=service,
        start_time=datetime(
            2026, 11, 26, 10 + i * 2, tzinfo=ZoneInfo("America/Edmonton")
        ),
        payment_status=pending,
        contact_name="SYNTHETIC Example Customer",
        contact_email="customer@example.invalid",
        contact_phone="+12025550123",
    )
    a.full_clean()
    appointments.append(a)
# Deliberately bulk seed after model validation: no post-save notification callbacks are dispatched.
Appointment.objects.bulk_create(appointments)
AppointmentStatusHistory.objects.bulk_create(
    [AppointmentStatusHistory(appointment=a, status=confirmed) for a in appointments]
)
contacts = SiteContactSettings.get_solo()
contacts.contact_email = "showcase@example.invalid"
contacts.office_phone = "+12025550123"
contacts.office_phone_display = "SYNTHETIC 202-555-0123"
contacts.text_phone = "+12025550123"
contacts.text_phone_display = "SYNTHETIC 202-555-0123"
contacts.save()
cat = Category.objects.create(
    name="SYNTHETIC Accessories",
    slug="synthetic-accessories",
    description="Local demonstration catalogue",
)
for i, (name, price) in enumerate(
    [
        ("SYNTHETIC All-Weather Mat Set", "149.00"),
        ("SYNTHETIC Cargo Organizer", "59.00"),
        ("SYNTHETIC Recovery Kit", "189.00"),
    ],
    1,
):
    Product.objects.create(
        name=name,
        sku=f"DEMO-{i:03d}",
        category=cat,
        price=Decimal(price),
        currency="CAD",
        inventory=10,
        is_active=True,
        is_in_house=True,
        tags=["SYNTHETIC"],
        description="SYNTHETIC demonstration item. No stock or payment is represented.",
    )
browser = Client()
browser.force_login(admin)
cookie = browser.cookies[settings.SESSION_COOKIE_NAME].value
(state / "browser-session.json").write_text(
    json.dumps(
        {
            "name": settings.SESSION_COOKIE_NAME,
            "value": cookie,
            "domain": "127.0.0.1",
            "path": "/",
            "httpOnly": True,
            "sameSite": "Lax",
        }
    )
    + "\n"
)
(state / "browser-session.json").chmod(0o600)
report = {
    "source": "BGM CRM synthetic workflow",
    "data_classification": "SYNTHETIC DEMO",
    "services": Service.objects.count(),
    "appointments": Appointment.objects.count(),
    "products": Product.objects.count(),
    "model_validation_executed": True,
    "notification_signals_dispatched": False,
    "external_provider_calls": 0,
    "database_namespace": "bgm_showcase",
    "site_contact_data": "SYNTHETIC example.invalid and reserved555numbers",
}
(state / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
