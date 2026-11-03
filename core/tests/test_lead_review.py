from types import SimpleNamespace
from unittest.mock import patch

from django.contrib import admin
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import LeadReviewCase, ServiceLead, ShopSharedDataRecord
from core.services.lead_review import (
    entity_admin_url,
    mark_lead_review_spam,
    notify_review_case,
    register_lead_review,
    release_lead_review,
    review_case_for,
)


class LeadReviewTests(TestCase):
    def setUp(self):
        self.lead = ServiceLead.objects.create(
            full_name="Real Customer", phone="4035550100", email="customer@example.com",
            service_needed="Bumper fitting", notes="Photos are available on request.",
        )
        self.assessment = SimpleNamespace(
            reasons=["known_campaign_link_domain"], known_campaign=True, fingerprint="a" * 64,
        )

    def _case(self):
        return register_lead_review("service_lead", self.lead.pk, assessment=self.assessment)

    def test_register_preserves_customer_and_uniquely_links_existing_inquiry(self):
        case = self._case()
        repeated = register_lead_review(
            "service_lead", self.lead.pk, evaluation=SimpleNamespace(reasons=["fast_submit"])
        )
        self.assertEqual(case.pk, repeated.pk)
        self.assertEqual(LeadReviewCase.objects.count(), 1)
        self.assertEqual(repeated.reasons, ["known_campaign_link_domain", "fast_submit"])
        self.assertTrue(repeated.known_campaign)
        self.assertEqual(repeated.status, LeadReviewCase.Status.PENDING)
        self.assertEqual(ServiceLead.objects.get(pk=self.lead.pk).notes, self.lead.notes)
        self.assertEqual(review_case_for("service_lead", self.lead.pk), repeated)
        self.assertIsNone(review_case_for("service_lead", 999999))

    def test_release_synchronizes_inquiry_once_and_notifies_team(self):
        case = self._case()
        with patch("notifications.services.notify_about_service_lead", return_value=2) as notify:
            self.assertTrue(release_lead_review(case))
            self.assertFalse(release_lead_review(case))
        self.assertEqual(case.status, LeadReviewCase.Status.RELEASED)
        self.assertIsNotNone(case.shop_synced_at)
        notify.assert_called_once_with(self.lead.pk)
        saved = ShopSharedDataRecord.objects.get()
        self.assertEqual(len(saved.payload["leads"]), 1)
        self.assertEqual(saved.payload["leads"][0]["name"], "Real Customer")

    def test_sync_failure_leaves_inquiry_pending_for_retry(self):
        case = self._case()
        with patch("core.services.shop_sync.sync_service_lead_to_shop", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                release_lead_review(case)
        case.refresh_from_db()
        self.assertEqual(case.status, LeadReviewCase.Status.PENDING)
        self.assertEqual(case.last_error, "RuntimeError")
        self.assertIsNone(case.shop_synced_at)
        self.assertTrue(ServiceLead.objects.filter(pk=self.lead.pk).exists())

    def test_notification_failure_retry_does_not_duplicate_shop_inquiry(self):
        case = self._case()
        with patch("notifications.services.notify_about_service_lead", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                release_lead_review(case)
        case.refresh_from_db()
        self.assertEqual(case.status, LeadReviewCase.Status.PENDING)
        self.assertIsNotNone(case.shop_synced_at)
        with patch("notifications.services.notify_about_service_lead", return_value=2):
            self.assertTrue(release_lead_review(case))
        self.assertEqual(len(ShopSharedDataRecord.objects.get().payload["leads"]), 1)

    def test_mark_spam_keeps_source_and_can_be_reversed_by_release(self):
        case = self._case()
        self.assertTrue(mark_lead_review_spam(case))
        self.assertEqual(case.status, LeadReviewCase.Status.SPAM)
        self.assertTrue(ServiceLead.objects.filter(pk=self.lead.pk).exists())
        with patch("notifications.services.notify_about_service_lead", return_value=2):
            self.assertTrue(release_lead_review(case))
        self.assertEqual(case.status, LeadReviewCase.Status.RELEASED)

    @override_settings(COMPANY_WEBSITE="badguymotors.com")
    @patch("notifications.services.send_telegram_message", return_value=2)
    def test_fallback_alert_uses_trusted_admin_link_and_delivery_deduplication(self, send):
        case = self._case()
        self.assertEqual(notify_review_case(case), 2)
        args, kwargs = send.call_args
        self.assertIn("https://badguymotors.com" + reverse("admin:core_leadreviewcase_change", args=[case.pk]), args[0])
        self.assertNotIn(self.lead.email, args[0])
        self.assertNotIn("partagepro.online", args[0])
        self.assertEqual(kwargs["dedupe_key"], f"lead-review:{case.pk}")
        self.assertEqual(kwargs["entity_type"], "lead_review_case")
        self.assertEqual(entity_admin_url(case), reverse("admin:core_servicelead_change", args=[self.lead.pk]))

    def test_admin_disables_deletion_of_review_evidence(self):
        model_admin = admin.site._registry[LeadReviewCase]
        self.assertFalse(model_admin.has_delete_permission(None, self._case()))
        self.assertFalse(model_admin.has_add_permission(None))
