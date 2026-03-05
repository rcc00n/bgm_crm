from __future__ import annotations

import json
from unittest.mock import patch

from django.test import SimpleTestCase, modify_settings, override_settings


@modify_settings(MIDDLEWARE={"remove": ["core.middleware.VisitorAnalyticsMiddleware"]})
@override_settings(
    PRINTFUL_WEBHOOK_SECRET="secret-123",
    SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
)
class PrintfulWebhookViewTests(SimpleTestCase):
    def test_webhook_accepts_post_without_csrf(self):
        with patch("store.views.record_printful_webhook") as record_printful_webhook:
            response = self.client.post(
                "/store/printful/webhook/secret-123/",
                data=json.dumps({"type": "order_updated", "order_id": 123}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        record_printful_webhook.assert_called_once()

    def test_webhook_rejects_wrong_secret(self):
        with patch("store.views.record_printful_webhook") as record_printful_webhook:
            response = self.client.post(
                "/store/printful/webhook/wrong-secret/",
                data=json.dumps({"type": "order_updated", "order_id": 123}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 403)
        record_printful_webhook.assert_not_called()
