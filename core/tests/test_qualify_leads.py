from datetime import timedelta

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Lead
from core.services.lead_security import build_form_token


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@example.com",
    LEAD_NOTIFICATION_EMAIL="ops@example.com",
    LEAD_FORM_MIN_AGE_SECONDS_SERVICE_LEAD=0,
    MARKETING={
        "site_name": "Bad Guy Motors",
        "default_description": "",
        "default_image": "/static/img/bad-guy-preview.png",
        "organization_logo": "/static/img/bad-guy-preview.png",
        "organization_same_as": [],
        "default_keywords": "",
        "google_tag_manager_id": "",
        "google_ads_id": "",
        "google_ads_conversion_label": "",
        "google_ads_send_page_view": False,
        "meta_pixel_id": "1234567890",
    },
)
class QualifyLeadFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        session = self.client.session
        session.save()

    def _token(self):
        session_key = self.client.session.session_key
        issued_at = timezone.now() - timedelta(seconds=10)
        return build_form_token(session_key=session_key, purpose="service_lead", issued_at=issued_at)

    def _payload(self, **overrides):
        payload = {
            "first_name": "Sam",
            "last_name": "Builder",
            "phone": "+1 (403) 555-0111",
            "email": "sam@example.com",
            "contact_pref": Lead.ContactPreference.TEXT,
            "truck_year": 2020,
            "truck_make": "Ford",
            "truck_model": "F-350",
            "mileage": Lead.Mileage.UNDER_150K,
            "industry": Lead.Industry.CONSTRUCTION,
            "frustration": "Truck is losing power under load.",
            "work_needed": [Lead.WorkNeeded.ENGINE_TRANS, Lead.WorkNeeded.PERFORMANCE],
            "timeline": Lead.Timeline.ASAP,
            "form_token": self._token(),
            "form_rendered_at": int(timezone.now().timestamp() * 1000) - 7000,
        }
        payload.update(overrides)
        return payload

    def test_qualify_submission_saves_lead_sends_email_and_redirects(self):
        response = self.client.post(reverse("qualify"), self._payload())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("qualify-thank-you"))

        self.assertEqual(Lead.objects.count(), 1)
        lead = Lead.objects.get()
        self.assertEqual(lead.name, "Sam Builder")
        self.assertEqual(lead.phone, "+14035550111")
        self.assertEqual(lead.email, "sam@example.com")
        self.assertEqual(lead.truck_make, "Ford")
        self.assertEqual(lead.truck_model, "F-350")
        self.assertEqual(lead.work_needed, [Lead.WorkNeeded.ENGINE_TRANS, Lead.WorkNeeded.PERFORMANCE])
        self.assertTrue(lead.flagged)

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["ops@example.com"])
        self.assertIn("New lead: Sam Builder", message.subject)
        self.assertIn("Flagged: Yes", message.body)
        self.assertIn("Work needed: Engine & Trans, Performance", message.body)

        thanks = self.client.get(reverse("qualify-thank-you"))
        self.assertEqual(thanks.status_code, 200)
        self.assertContains(thanks, "Thank You")
        self.assertContains(thanks, "fbq('track', 'Lead')")

    def test_invalid_submission_does_not_create_lead(self):
        response = self.client.post(
            reverse("qualify"),
            self._payload(last_name="", frustration=""),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Lead.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(response, "Last name is required.")
        self.assertContains(response, "Tell us your biggest frustration.")

    def test_thank_you_requires_successful_submission(self):
        response = self.client.get(reverse("qualify-thank-you"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("qualify"))

    def test_meta_pixel_renders_on_qualify_without_lead_event(self):
        response = self.client.get(reverse("qualify"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "fbq('init', '1234567890')")
        self.assertNotContains(response, "fbq('track', 'Lead')")
