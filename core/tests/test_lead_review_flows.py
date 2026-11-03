from datetime import timedelta
from decimal import Decimal
import hashlib
from unittest.mock import patch

from django.core.cache import caches
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Lead, LeadReviewCase, LeadSubmissionEvent, ServiceLead
from core.services.lead_security import build_form_token
from core.tests.test_lead_security_shared import TEST_CACHES
from store.models import Category, CustomFitmentRequest, Product


@override_settings(
    CACHES=TEST_CACHES,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@example.com",
    SECURE_SSL_REDIRECT=False,
)
class LeadReviewFlowTests(TestCase):
    def setUp(self):
        for alias in TEST_CACHES:
            caches[alias].clear()
        session = self.client.session
        session.save()
        category = Category.objects.create(name="Review fixtures", slug="review-fixtures")
        self.product = Product.objects.create(
            name="Headache Racks", slug="review-headache-racks", sku="REVIEW-FLOW-1",
            category=category, price=Decimal("500.00"),
        )
        self.fitment_url = reverse("store:store-product", kwargs={"slug": self.product.slug})
        self.telegram = self._patch("notifications.services.send_telegram_message", return_value=2)
        self._patch("notifications.services.send_staff_email_notification", return_value=1)
        self.fitment_sync = self._patch("store.views.queue_shop_sync")
        self.other_sync = self._patch("core.views.queue_shop_sync")
        self.fitment_digest = self._patch("store.views.notification_services.queue_lead_digest", return_value=True)
        self.other_digest = self._patch("core.views.queue_lead_digest", return_value=True)
        self.fitment_internal_email = self._patch("store.views._notify_fitment_request")
        self.fitment_customer_email = self._patch("store.views._send_fitment_request_received_email")
        self.qualify_email = self._patch("core.views._notify_about_qualify_lead")

    def _patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def _security_fields(self, purpose, *, fast=False):
        return {
            "form_token": build_form_token(
                session_key=self.client.session.session_key, purpose=purpose,
                issued_at=timezone.now() - timedelta(seconds=15),
            ),
            "form_rendered_at": int(timezone.now().timestamp() * 1000) - (1000 if fast else 8000),
        }

    def _post(self, url, payload, *, include_headers=True):
        headers = {"HTTP_USER_AGENT": "Customer browser"}
        if include_headers:
            headers.update(HTTP_REFERER="http://testserver" + url, HTTP_ORIGIN="http://testserver")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, payload, **headers)
        if response.status_code != 302:
            errors = []
            if response.context:
                for name in ("quote_form", "form"):
                    form = response.context.get(name)
                    if form is not None:
                        errors.append(str(form.errors))
            self.fail(f"Expected saved-inquiry redirect, got {response.status_code}; forms={errors}; events={list(LeadSubmissionEvent.objects.values('outcome', 'validation_errors', 'flags'))}")
        return response

    def _post_fitment(self, *, message, email="customer@example.com", fast=False, include_headers=True):
        return self._post(self.fitment_url, {
            "form_type": "custom_fitment", "customer_name": "Customer Builder", "email": email,
            "phone": "+14035550111", "vehicle": "2020 Ford F-350", "budget": "$5000",
            "timeline": "1 to 2 months", "message": message,
            "source_url": "https://badguymotors.com" + self.fitment_url,
            **self._security_fields("fitment_request", fast=fast),
        }, include_headers=include_headers)

    def _service_payload(self, *, notes="Need a bumper quote.", email="customer@example.com"):
        return {
            "full_name": "Customer Builder", "phone": "+14035550111", "email": email,
            "vehicle": "2020 Ford F-350", "service_needed": "Bumper fitting", "notes": notes,
            "source_page": ServiceLead.SourcePage.GENERAL_REQUEST,
            "source_url": "https://badguymotors.com/request/",
            **self._security_fields("service_lead"),
        }

    def _qualify_payload(self):
        return {
            "first_name": "Benoit", "last_name": "Henry", "phone": "+14035550111",
            "email": "benoit.henry7813@prodmail.online", "contact_pref": Lead.ContactPreference.EMAIL,
            "truck_year": 2020, "truck_make": "Ford", "truck_model": "F-350",
            "mileage": Lead.Mileage.BETWEEN_150K_250K, "industry": Lead.Industry.PERSONAL,
            "frustration": "Quote details https://partagepro.online/en/loc/badguymotors",
            "work_needed": [Lead.WorkNeeded.SUSPENSION], "timeline": Lead.Timeline.ONE_TO_THREE_MONTHS,
            **self._security_fields("service_lead"),
        }

    def _assert_linked_event(self, entity_type, entity, case):
        event = LeadSubmissionEvent.objects.latest("created_at")
        self.assertEqual(event.outcome, "suspected")
        self.assertTrue(event.success)
        self.assertEqual(event.flags["entity_type"], entity_type)
        self.assertEqual(event.flags["entity_id"], str(entity.pk))
        self.assertEqual(event.flags["review_case_id"], str(case.pk))

    def test_benoit_style_valid_request_is_saved_for_review_without_phishing_distribution(self):
        message = "A four-link lift kit quote, project details: https://partagepro.online/en/loc/badguymotors"
        response = self._post_fitment(message=message, email="benoit.henry7813@prodmail.online")
        self.assertEqual(response.status_code, 302)
        inquiry = CustomFitmentRequest.objects.get()
        self.assertEqual(inquiry.message, message)
        case = LeadReviewCase.objects.get(entity_type="fitment_request", entity_id=str(inquiry.pk))
        self.assertEqual(case.status, LeadReviewCase.Status.PENDING)
        self.assertTrue(case.known_campaign)
        self.fitment_sync.assert_not_called()
        self.fitment_customer_email.assert_not_called()
        self.fitment_internal_email.assert_not_called()
        self.telegram.assert_not_called()
        self.assertEqual(self.fitment_digest.call_args.kwargs["outcome"], "saved_for_review")
        self._assert_linked_event("fitment_request", inquiry, case)

    def test_redis_queue_failure_keeps_inquiry_and_sends_safe_review_fallback(self):
        self.fitment_digest.return_value = False
        response = self._post_fitment(
            message="Project https://partagepro.online/en/loc/badguymotors",
            email="benoit.henry7813@prodmail.online",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CustomFitmentRequest.objects.count(), 1)
        case = LeadReviewCase.objects.get()
        self.telegram.assert_called_once()
        args, kwargs = self.telegram.call_args
        self.assertIn("Saved inquiry awaiting review", args[0])
        self.assertIn(reverse("admin:core_leadreviewcase_change", args=[case.pk]), args[0])
        self.assertNotIn("partagepro.online", args[0])
        self.assertNotIn("benoit.henry", args[0])
        self.assertEqual(kwargs["dedupe_key"], f"lead-review:{case.pk}")
        self.fitment_sync.assert_not_called()
        self.fitment_customer_email.assert_not_called()

    def test_customer_external_documents_keep_normal_immediate_notification_and_sync(self):
        response = self._post_fitment(message="Truck pictures: https://drive.google.com/folder/customer123")
        self.assertEqual(response.status_code, 302)
        inquiry = CustomFitmentRequest.objects.get()
        self.assertFalse(LeadReviewCase.objects.exists())
        self.fitment_sync.assert_called_once()
        self.assertEqual(self.fitment_sync.call_args.args[1], inquiry.pk)
        self.fitment_customer_email.assert_called_once_with(inquiry)
        self.fitment_internal_email.assert_called_once_with(inquiry)
        self.telegram.assert_called_once()
        self.assertIn("New fitment request", self.telegram.call_args.args[0])
        self.assertIn("https://drive.google.com/folder/customer123", self.telegram.call_args.args[0])
        self.fitment_digest.assert_not_called()
        event = LeadSubmissionEvent.objects.get()
        self.assertEqual(event.outcome, "accepted")
        self.assertEqual(event.flags["entity_id"], str(inquiry.pk))

    def test_heuristic_suspect_is_saved_and_immediately_alerted_with_review_context(self):
        ua_key = hashlib.sha256(b"Customer browser").hexdigest()[:16]
        caches["lead_security"].set(f"lead:ua:{ua_key}", 25, timeout=600)
        response = self._post_fitment(
            message="Please quote my bumper fitting.", fast=True, include_headers=False,
        )
        self.assertEqual(response.status_code, 302)
        inquiry = CustomFitmentRequest.objects.get()
        case = LeadReviewCase.objects.get()
        self.assertFalse(case.known_campaign)
        self.assertIn("fast_submit", case.reasons)
        self.fitment_sync.assert_not_called()
        self.fitment_customer_email.assert_called_once_with(inquiry)
        self.telegram.assert_called_once()
        message = self.telegram.call_args.args[0]
        self.assertIn("Lead needs review", message)
        self.assertIn(inquiry.email, message)
        self.assertIn("New fitment request", message)
        self._assert_linked_event("fitment_request", inquiry, case)
        self.assertGreaterEqual(LeadSubmissionEvent.objects.get().suspicion_score, 6)

    def test_known_campaign_service_inquiry_is_preserved_without_sync_or_full_alert(self):
        response = self._post(reverse("service-lead-submit"), self._service_payload(
            notes="Project https://partagepro.online/en/loc/badguymotors",
            email="benoit.henry7813@prodmail.online",
        ))
        self.assertEqual(response.status_code, 302)
        inquiry = ServiceLead.objects.get()
        case = LeadReviewCase.objects.get(entity_type="service_lead", entity_id=str(inquiry.pk))
        self.assertTrue(case.known_campaign)
        self.other_sync.assert_not_called()
        self.telegram.assert_not_called()
        self.other_digest.assert_called_once()
        self._assert_linked_event("service_lead", inquiry, case)

    def test_known_campaign_qualification_inquiry_is_preserved_without_sync_or_full_alert(self):
        response = self._post(reverse("qualify"), self._qualify_payload())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("qualify-thank-you"))
        inquiry = Lead.objects.get()
        case = LeadReviewCase.objects.get(entity_type="lead", entity_id=str(inquiry.pk))
        self.assertTrue(case.known_campaign)
        self.other_sync.assert_not_called()
        self.qualify_email.assert_not_called()
        self.telegram.assert_not_called()
        self.other_digest.assert_called_once()
        self._assert_linked_event("lead", inquiry, case)

    def test_valid_customer_retries_exceeding_shared_rate_limit_are_saved_and_alerted(self):
        for _ in range(3):
            response = self._post(reverse("service-lead-submit"), self._service_payload())
            self.assertEqual(response.status_code, 302)
        self.assertEqual(ServiceLead.objects.count(), 3)
        case = LeadReviewCase.objects.get()
        self.assertEqual(case.entity_type, "service_lead")
        self.assertIn("rate_limit", case.reasons)
        self.assertFalse(case.known_campaign)
        self.assertEqual(self.other_sync.call_count, 2)
        self.assertEqual(self.telegram.call_count, 3)
        self.assertIn("Lead needs review", self.telegram.call_args.args[0])
        latest = ServiceLead.objects.latest("created_at")
        self.assertEqual(case.entity_id, str(latest.pk))
        self._assert_linked_event("service_lead", latest, case)
