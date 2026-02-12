import json
from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Appointment,
    CustomUserDisplay,
    MasterProfile,
    PaymentStatus,
    Service,
    ServiceMaster,
)


class BookingApiTests(TestCase):
    def setUp(self):
        self.availability_url = reverse("api-availability")
        self.book_url = reverse("api-book")
        self.day = timezone.localdate() + timedelta(days=1)

        self.service = Service.objects.create(
            name="Test Service",
            base_price="120.00",
            duration_min=30,
        )
        PaymentStatus.objects.create(name="Pending")

        self.idle_master = self._create_master(
            username="idle_master",
            work_start=time(8, 0),
            work_end=time(8, 0),  # no working window
        )
        self.available_master = self._create_master(
            username="available_master",
            work_start=time(9, 0),
            work_end=time(18, 0),
        )

        ServiceMaster.objects.create(service=self.service, master=self.idle_master)
        ServiceMaster.objects.create(service=self.service, master=self.available_master)

    def _create_master(self, *, username: str, work_start: time, work_end: time) -> CustomUserDisplay:
        user = User.objects.create_user(username=username, password="pass1234")
        master = CustomUserDisplay.objects.get(pk=user.pk)
        MasterProfile.objects.create(
            user=master,
            work_start=work_start,
            work_end=work_end,
        )
        return master

    def _contact_payload(self) -> dict[str, str]:
        return {
            "name": "John Doe",
            "email": "john@example.com",
            "phone": "+15551234567",
        }

    def test_api_book_auto_assigns_master_when_master_not_provided(self):
        availability_response = self.client.get(
            self.availability_url,
            {"service": str(self.service.pk), "date": self.day.isoformat()},
        )
        self.assertEqual(availability_response.status_code, 200)

        masters = availability_response.json().get("masters", [])
        open_master = next(
            (row for row in masters if int(row["id"]) == self.available_master.id),
            None,
        )
        self.assertIsNotNone(open_master)
        self.assertTrue(open_master["slots"])
        slot_iso = open_master["slots"][0]

        book_response = self.client.post(
            self.book_url,
            data=json.dumps(
                {
                    "service": str(self.service.pk),
                    "start_time": slot_iso,
                    "contact": self._contact_payload(),
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(book_response.status_code, 201)

        appointment = Appointment.objects.get()
        self.assertEqual(appointment.master_id, self.available_master.id)
        self.assertEqual(appointment.service_id, self.service.id)

    def test_api_book_returns_error_when_no_master_is_available_for_slot(self):
        unavailable_start = timezone.make_aware(datetime.combine(self.day, time(3, 0)))
        book_response = self.client.post(
            self.book_url,
            data=json.dumps(
                {
                    "service": str(self.service.pk),
                    "start_time": unavailable_start.isoformat(),
                    "contact": self._contact_payload(),
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(book_response.status_code, 400)
        payload = book_response.json()
        self.assertIn("No staff is available", payload.get("error", ""))
