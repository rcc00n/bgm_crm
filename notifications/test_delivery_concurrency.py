import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase

from notifications.delivery import send_message
from notifications.models import TelegramBotSettings, TelegramMessageLog


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL concurrent row claims")
class ConcurrentTelegramDeliveryTests(TransactionTestCase):
    def test_eight_workers_claim_one_recipient_message_once(self):
        settings = TelegramBotSettings.objects.create(
            enabled=True, bot_token="123456:test-only", admin_chat_ids="101",
        )
        barrier = threading.Barrier(8)
        calls = []
        calls_lock = threading.Lock()

        class FakeBot:
            def send_message(self, chat_id, text, **kwargs):
                with calls_lock:
                    calls.append((chat_id, text))
                # Give competing workers time to encounter the active claim.
                time.sleep(0.05)
                return SimpleNamespace(message_id=321)

        def deliver_from_worker():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return send_message(
                    "One real inquiry",
                    event_type="fitment_request",
                    dedupe_key="fitment_request:concurrent-test",
                    entity_type="fitment_request",
                    entity_id="concurrent-test",
                )
            finally:
                # PostgreSQL test DB teardown must not retain worker sessions.
                connections.close_all()

        with patch("notifications.services.build_bot", return_value=(FakeBot(), settings)):
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(deliver_from_worker) for _ in range(8)]
                delivered = [future.result(timeout=20) for future in futures]

        self.assertEqual(sum(delivered), 1)
        self.assertEqual(calls, [(101, "One real inquiry")])
        self.assertEqual(TelegramMessageLog.objects.count(), 1)
        row = TelegramMessageLog.objects.get()
        self.assertEqual(row.status, TelegramMessageLog.Status.SENT)
        self.assertTrue(row.success)
        self.assertEqual(row.attempts, 1)
        self.assertEqual(row.telegram_message_id, 321)
