from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.models import StaffLoginEvent


class StaffLoginHistoryTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user_model = get_user_model()

    def test_staff_login_signal_creates_event(self):
        staff_user = self.user_model.objects.create_user(
            username="staff-login-user",
            email="staff.login@example.com",
            password="pass12345",
            is_staff=True,
        )
        request = self.factory.get(
            "/admin/login/",
            HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0 Safari/537.36",
            REMOTE_ADDR="203.0.113.10",
        )

        user_logged_in.send(sender=staff_user.__class__, request=request, user=staff_user)

        event = StaffLoginEvent.objects.get()
        self.assertEqual(event.user, staff_user)
        self.assertEqual(event.ip_address, "203.0.113.10")
        self.assertEqual(event.login_path, "/admin/login/")
        self.assertIn("Chrome", event.user_agent)

    def test_non_staff_login_does_not_create_event(self):
        client_user = self.user_model.objects.create_user(
            username="client-login-user",
            email="client.login@example.com",
            password="pass12345",
            is_staff=False,
        )
        request = self.factory.get("/accounts/login/", REMOTE_ADDR="203.0.113.20")

        user_logged_in.send(sender=client_user.__class__, request=request, user=client_user)

        self.assertFalse(StaffLoginEvent.objects.exists())

    def test_staff_usage_page_shows_login_history(self):
        superuser = self.user_model.objects.create_superuser(
            username="admin-login-history",
            email="admin.login.history@example.com",
            password="pass12345",
        )
        staff_user = self.user_model.objects.create_user(
            username="employee-login-history",
            email="employee.login.history@example.com",
            password="pass12345",
            first_name="Denim",
            last_name="Kermeen",
            is_staff=True,
        )
        StaffLoginEvent.objects.create(
            user=staff_user,
            ip_address="198.51.100.20",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0 Safari/537.36",
            login_path="/admin/login/",
        )
        self.client.force_login(superuser)

        response = self.client.get(reverse("admin-staff-usage"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staff login history")
        self.assertContains(response, "198.51.100.20")
        self.assertContains(response, "Desktop")
        self.assertContains(response, "Chrome on Windows")
