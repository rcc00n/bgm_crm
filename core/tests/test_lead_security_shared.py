from datetime import timedelta
from unittest.mock import Mock, patch

from django.core.cache import caches
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import timezone

from core.services import lead_security


TEST_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "lead-security-unrelated-default",
    },
    "lead_security": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "lead-security-shared-tests",
    },
}


@override_settings(CACHES=TEST_CACHES)
class LeadSecuritySharedCacheTests(SimpleTestCase):
    def setUp(self):
        caches["default"].clear()
        caches["lead_security"].clear()

    def _token(self):
        return lead_security.build_form_token(
            session_key="valid-customer-session",
            purpose="fitment_request",
            issued_at=timezone.now() - timedelta(seconds=15),
        )

    def test_nonce_replay_uses_security_alias_across_cache_lookups(self):
        token = self._token()
        kwargs = {"session_key": "valid-customer-session", "purpose": "fitment_request"}
        first = lead_security.validate_form_token(token, **kwargs)
        # The unrelated application cache must not own replay protection.
        caches["default"].clear()
        second = lead_security.validate_form_token(token, **kwargs)
        self.assertTrue(first.valid)
        self.assertFalse(second.valid)
        self.assertEqual(second.error, "replay")

    def test_security_counter_does_not_use_application_default_cache(self):
        self.assertEqual(lead_security._increment_counter("test-counter", 60), 1)
        caches["default"].clear()
        self.assertEqual(lead_security._increment_counter("test-counter", 60), 2)
        self.assertIsNone(caches["default"].get("test-counter"))

    def test_valid_token_and_rate_counters_fail_open_on_cache_outage(self):
        token = self._token()
        with patch.object(lead_security, "_security_cache", side_effect=ConnectionError("private-connection-url")):
            with patch.object(lead_security, "_last_cache_warning", 0):
                with self.assertLogs(lead_security.logger, level="WARNING") as captured:
                    result = lead_security.validate_form_token(
                        token, session_key="valid-customer-session", purpose="fitment_request"
                    )
                    limits = lead_security.check_rate_limits(
                        purpose="fitment_request", ip_address="192.0.2.1", subnet="192.0.2.0/24",
                        session_key="valid-customer-session", asn=None,
                    )
        self.assertTrue(result.valid)
        self.assertFalse(limits.exceeded)
        self.assertEqual(limits.counts, {"ip": 0, "subnet": 0, "session": 0})
        self.assertNotIn("private-connection-url", " ".join(captured.output))
        self.assertEqual(len(captured.output), 1)

    def test_missing_counter_between_add_and_increment_is_retried_atomically(self):
        backend = Mock()
        backend.add.side_effect = [False, True]
        backend.incr.side_effect = ValueError("key expired")
        with patch.object(lead_security, "_security_cache", return_value=backend):
            self.assertEqual(lead_security._increment_counter("expiring-counter", 60), 1)
        backend.set.assert_not_called()

    def test_valid_customer_with_multiple_heuristic_signals_is_preserved_for_review(self):
        request = RequestFactory().post(
            "/store/p/headache-racks/", {"email": "customer@example.com"}
        )
        request.session = Mock(session_key="valid-customer-session")
        request.session.get.return_value = None
        with patch.object(lead_security, "validate_form_token", return_value=lead_security.TokenValidation(True, None, 15)):
            with patch.object(lead_security, "format_ip_location", return_value=""):
                with patch.object(lead_security, "parse_time_on_page_ms", return_value=1000):
                    result = lead_security.evaluate_lead_submission(
                        request, purpose="fitment_request", email="customer@example.com"
                    )
        # Missing headers + missing cookie + fast submission exceeds block score.
        self.assertGreaterEqual(result.score, lead_security.BLOCK_SCORE_THRESHOLD)
        self.assertEqual(result.action, "suspect")
        self.assertTrue(result.token_valid)
        self.assertFalse(result.honeypot_hit)

    def test_submission_log_links_saved_entity_and_review_without_schema_changes(self):
        request = RequestFactory().post("/store/p/headache-racks/", {})
        request.session = Mock(session_key="valid-customer-session")
        request.session.get.return_value = None
        with patch.object(lead_security, "validate_form_token", return_value=lead_security.TokenValidation(True, None, 15)):
            with patch.object(lead_security, "format_ip_location", return_value=""):
                evaluation = lead_security.evaluate_lead_submission(
                    request, purpose="fitment_request", email="customer@example.com"
                )
        with patch("core.models.LeadSubmissionEvent.objects.create") as create:
            lead_security.log_lead_submission(
                form_type="fitment_request", evaluation=evaluation, outcome="suspected", success=True,
                entity_type="fitment_request", entity_id=123, review_case_id=45,
            )
        flags = create.call_args.kwargs["flags"]
        self.assertEqual(flags["entity_type"], "fitment_request")
        self.assertEqual(flags["entity_id"], "123")
        self.assertEqual(flags["review_case_id"], "45")

    def test_shared_rate_limit_preserves_valid_customer_for_review(self):
        request = RequestFactory().post("/services/lead/", {})
        request.session = Mock(session_key="valid-customer-session")
        request.session.get.return_value = None
        with patch.object(lead_security, "validate_form_token", return_value=lead_security.TokenValidation(True, None, 15)):
            with patch.object(lead_security, "format_ip_location", return_value=""):
                with patch.object(lead_security, "check_rate_limits", return_value=lead_security.RateLimitResult(True, ["session"], {"session": 3})):
                    evaluation = lead_security.evaluate_lead_submission(
                        request, purpose="service_lead", email="customer@example.com"
                    )
        self.assertEqual(evaluation.action, "suspect")
        self.assertIn("rate_limit", evaluation.reasons)

    @override_settings(CACHES={"default": TEST_CACHES["default"]})
    def test_development_without_security_alias_can_use_default(self):
        self.assertEqual(lead_security._increment_counter("development-counter", 60), 1)


@override_settings(CACHES=TEST_CACHES)
class LeadContentAssessmentTests(SimpleTestCase):
    def setUp(self):
        caches["lead_security"].clear()

    def test_known_campaign_message_is_routed_for_review(self):
        result = lead_security.assess_lead_content(
            text="Quote and build timeline, project details: https://partagepro.online/en/loc/badguymotors",
            email="benoit.henry7813@prodmail.online", phone="0733826732",
        )
        self.assertTrue(result.requires_review)
        self.assertEqual(result.link_domains, ["partagepro.online"])
        self.assertEqual(
            result.reasons, ["known_campaign_email_domain", "known_campaign_link_domain"]
        )

    def test_known_domain_normalization_and_actual_url_hostname(self):
        for url in [
            "HTTPS://Files.PartagePro.Online./project",
            "//files.northshare.online/project",
            "monpartage.online/fr/project",
            "https://mondocs.my.id/files",
        ]:
            with self.subTest(url=url):
                self.assertTrue(lead_security.assess_lead_content(text=url).requires_review)
        for url in [
            "https://partagepro.online.evil.example/project",
            "https://notpartagepro.online/project",
            "https://partagepro.online@customer.example/project",
            "https://customer.example/path/partagepro.online",
        ]:
            with self.subTest(url=url):
                self.assertFalse(lead_security.assess_lead_content(text=url).requires_review)

    def test_genuine_customer_external_links_and_name_do_not_trigger_review(self):
        result = lead_security.assess_lead_content(
            text="My name is Benoit Henry. My truck photos: https://drive.google.com/folder/123 "
                 "and parts are at https://customer.online/build.",
            email="customer@example.com", phone="+1 403 555 0100",
        )
        self.assertFalse(result.requires_review)
        self.assertFalse(result.known_campaign)
        self.assertEqual(result.link_domains, ["customer.online", "drive.google.com"])

    def test_repeated_content_is_a_signal_without_rejecting_real_customer(self):
        inputs = {"text": "Please quote a bumper. https://photos.example.com/a", "phone": "403-555-0100"}
        results = [lead_security.assess_lead_content(**inputs) for _ in range(3)]
        self.assertEqual([result.repeat_count for result in results], [1, 2, 3])
        self.assertIn("repeated_content", results[-1].reasons)
        self.assertFalse(results[-1].requires_review)
        self.assertEqual(len(results[-1].fingerprint), 64)

    def test_cache_outage_does_not_prevent_content_assessment(self):
        with patch.object(lead_security, "_security_cache", side_effect=ConnectionError):
            result = lead_security.assess_lead_content(
                text="https://partagepro.online/project", email="customer@example.com"
            )
        self.assertTrue(result.requires_review)
        self.assertEqual(result.repeat_count, 0)

    def test_malformed_url_is_harmless(self):
        result = lead_security.assess_lead_content(text="Truck photos https://[malformed/url")
        self.assertFalse(result.requires_review)
