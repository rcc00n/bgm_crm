from datetime import timedelta

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import SiteNoticeSignup
from core.services.lead_security import build_form_token


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@example.com",
    SITE_NOTICE_PROMO_CODE="WELCOME5",
    LEAD_FORM_MIN_AGE_SECONDS_SITE_NOTICE=0,
)
class SiteNoticeSignupTests(TestCase):
    def setUp(self):
        cache.clear()
        session = self.client.session
        session.save()

    def _token(self):
        session_key = self.client.session.session_key
        issued_at = timezone.now() - timedelta(seconds=10)
        return build_form_token(session_key=session_key, purpose="site_notice", issued_at=issued_at)

    def test_signup_sends_code_email(self):
        url = reverse("site-notice-signup")
        response = self.client.post(
            url,
            {
                "email": "test@example.com",
                "form_token": self._token(),
                "form_rendered_at": int(timezone.now().timestamp() * 1000) - 7000,
            },
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
            {
                "email": "not-an-email",
                "form_token": self._token(),
                "form_rendered_at": int(timezone.now().timestamp() * 1000) - 7000,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(SiteNoticeSignup.objects.count(), 0)
