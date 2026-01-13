import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import PageView, VisitorSession
from core.services.analytics import summarize_web_analytics, summarize_web_analytics_periods


class AnalyticsCollectViewTests(TestCase):
    def setUp(self):
        self.url = reverse("analytics-collect")
        self.payload = {
            "page_instance_id": "test-page",
            "path": "/",
            "full_path": "/?utm=test",
            "title": "Homepage",
            "referrer": "https://example.com",
            "duration_ms": 1200,
            "started_at": timezone.now().isoformat(),
            "timezone_offset": -360,
            "viewport_width": 1440,
            "viewport_height": 900,
        }

    def test_creates_page_view_and_session(self):
        response = self.client.post(
            self.url,
            data=json.dumps(self.payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(PageView.objects.count(), 1)
        page_view = PageView.objects.select_related("session").first()
        self.assertIsNotNone(page_view.session)
        self.assertEqual(page_view.session.session_key, self.client.session.session_key)
        self.assertEqual(page_view.duration_ms, 1200)

    def test_updates_existing_page_view(self):
        self.client.post(self.url, data=json.dumps(self.payload), content_type="application/json")
        updated_payload = dict(self.payload)
        updated_payload["duration_ms"] = 6400
        response = self.client.post(
            self.url,
            data=json.dumps(updated_payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        page_view = PageView.objects.get(page_instance_id=self.payload["page_instance_id"])
        self.assertEqual(page_view.duration_ms, 6400)

    def test_attaches_user_when_authenticated(self):
        user = User.objects.create_user("tester", email="tester@example.com", password="pass1234")
        self.client.login(username="tester", password="pass1234")
        payload = dict(self.payload)
        payload["page_instance_id"] = "auth-page"
        self.client.post(self.url, data=json.dumps(payload), content_type="application/json")
        page_view = PageView.objects.get(page_instance_id="auth-page")
        self.assertEqual(page_view.user, user)
        self.assertEqual(page_view.session.user, user)


class AnalyticsSummaryTests(TestCase):
    def test_summary_returns_expected_totals(self):
        session = VisitorSession.objects.create(
            session_key="summary-session",
            landing_path="/services",
            user_agent="pytest",
        )
        PageView.objects.create(
            session=session,
            user=None,
            page_instance_id="summary-pv",
            path="/services",
            full_path="/services",
            page_title="Services",
            referrer="",
            started_at=timezone.now() - timedelta(hours=1),
            duration_ms=4500,
            timezone_offset=-360,
            viewport_width=1280,
            viewport_height=720,
        )

        summary = summarize_web_analytics(window_days=7)
        self.assertTrue(summary["has_data"])
        self.assertEqual(summary["totals"]["visits"], 1)
        self.assertEqual(summary["totals"]["page_views"], 1)
        self.assertAlmostEqual(summary["totals"]["avg_duration_seconds"], 4.5)
        self.assertAlmostEqual(summary["engagement"]["average_seconds"], 4.5)
        self.assertAlmostEqual(summary["engagement"]["median_seconds"], 4.5)
        self.assertEqual(summary["engagement"]["sample_size"], 1)
        self.assertEqual(summary["traffic_highlights"]["busiest_day"]["count"], 1)


class AnalyticsPeriodSummaryTests(TestCase):
    def test_period_helper_returns_multiple_windows(self):
        session = VisitorSession.objects.create(
            session_key="period-session",
            landing_path="/",
            user_agent="pytest",
        )
        PageView.objects.create(
            session=session,
            user=None,
            page_instance_id="period-pv",
            path="/",
            full_path="/",
            page_title="Home",
            referrer="",
            started_at=timezone.now() - timedelta(minutes=5),
            duration_ms=3000,
            timezone_offset=-360,
            viewport_width=1280,
            viewport_height=720,
        )

        cached_week = summarize_web_analytics(window_days=7)
        periods = summarize_web_analytics_periods([1, 7, 30], cache={7: cached_week})

        self.assertEqual(len(periods), 3)
        self.assertEqual(periods[0]["label"], "Today")
        self.assertEqual(periods[1]["label"], "Last 7 days")
        self.assertEqual(periods[2]["label"], "Last 30 days")
        self.assertEqual(periods[0]["totals"].get("visits"), 1)
        self.assertEqual(periods[0]["engagement"].get("sample_size"), 1)
