from datetime import timedelta

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import SiteNoticeSignup


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@example.com",
    COMPANY_WEBSITE="https://example.com",
)
class SiteNoticeFollowupCommandTests(TestCase):
    def test_followups_send_on_schedule(self):
        now = timezone.now()
        signup = SiteNoticeSignup.objects.create(
            email="followup@example.com",
            welcome_code="WELCOME5",
            welcome_sent_at=now - timedelta(days=2),
        )

        call_command("send_site_notice_followups")
        self.assertEqual(len(mail.outbox), 1)
        signup.refresh_from_db()
        self.assertIsNotNone(signup.followup_2_sent_at)
        self.assertIsNone(signup.followup_3_sent_at)

        mail.outbox.clear()
        signup.welcome_sent_at = now - timedelta(days=4)
        signup.followup_2_sent_at = now - timedelta(days=2)
        signup.save(update_fields=["welcome_sent_at", "followup_2_sent_at"])

        call_command("send_site_notice_followups")
        self.assertEqual(len(mail.outbox), 1)
        signup.refresh_from_db()
        self.assertIsNotNone(signup.followup_3_sent_at)
