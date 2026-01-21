from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import SiteNoticeSignup


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@example.com",
    SITE_NOTICE_PROMO_CODE="WELCOME5",
)
class SiteNoticeSignupTests(TestCase):
    def test_signup_sends_code_email(self):
        url = reverse("site-notice-signup")
        response = self.client.post(
            url,
            {"email": "test@example.com"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn("welcome code", message.subject.lower())
        self.assertIn("WELCOME5", message.body)
        self.assertEqual(SiteNoticeSignup.objects.count(), 1)
        signup = SiteNoticeSignup.objects.get()
        self.assertEqual(signup.email, "test@example.com")
        self.assertEqual(signup.welcome_code, "WELCOME5")

    def test_invalid_email_returns_error(self):
        url = reverse("site-notice-signup")
        response = self.client.post(
            url,
            {"email": "not-an-email"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(SiteNoticeSignup.objects.count(), 0)
