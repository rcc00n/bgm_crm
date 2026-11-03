from datetime import datetime, timedelta, timezone as datetime_timezone
from concurrent.futures import ThreadPoolExecutor
import os
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import Mock, patch
import uuid

from django.test import SimpleTestCase
from django.utils import timezone

from notifications import lead_digest


class LeadDigestTests(SimpleTestCase):
    def setUp(self):
        self.timezone_override = timezone.override("America/Edmonton")
        self.timezone_override.__enter__()
        self.addCleanup(self.timezone_override.__exit__, None, None, None)
        self.client = Mock()
        self.backend_patch = patch(
            "notifications.lead_digest._backend",
            return_value=(self.client, lambda key: "test:" + key),
        )
        self.backend_patch.start()
        self.addCleanup(self.backend_patch.stop)
        warning_patch = patch.dict(lead_digest._WARNING_LAST, {}, clear=True)
        warning_patch.start()
        self.addCleanup(warning_patch.stop)

    def local(self, year, month, day, hour, minute=0):
        return timezone.make_aware(datetime(year, month, day, hour, minute))

    def test_windows_end_at_next_scheduled_slot_including_exact_boundary(self):
        before = self.local(2026, 11, 2, 14, 59)
        self.assertEqual(lead_digest._slot_end(before), self.local(2026, 11, 2, 15))
        self.assertEqual(
            lead_digest._slot_end(self.local(2026, 11, 2, 15)),
            self.local(2026, 11, 2, 21),
        )
        self.assertEqual(
            lead_digest._slot_end(self.local(2026, 11, 2, 21)),
            self.local(2026, 11, 3, 15),
        )

    def test_windows_keep_local_hours_when_daylight_saving_time_changes(self):
        end = lead_digest._slot_end(self.local(2025, 11, 1, 22))
        start = lead_digest._previous_end(end)
        self.assertEqual((end.day, end.hour), (2, 15))
        self.assertEqual((start.day, start.hour), (1, 21))
        self.assertEqual(
            end.astimezone(datetime_timezone.utc) - start.astimezone(datetime_timezone.utc),
            timedelta(hours=19),
        )

    @patch("notifications.services.send_telegram_message")
    @patch("notifications.lead_digest.timezone.now")
    def test_form_only_updates_shared_counters_and_never_sends(self, now, send):
        now.return_value = self.local(2026, 10, 28, 23)
        queued = lead_digest.queue_lead_digest(
            form_type="fitment_request",
            suspicious=True,
            outcome="saved_for_review",
            entity_id=5895,
            ip_address="192.0.2.1",
        )
        send.assert_not_called()
        self.assertTrue(queued)
        call = self.client.eval.call_args.args
        self.assertEqual(call[0], lead_digest.QUEUE_SCRIPT)
        self.assertEqual(call[1], 4)
        self.assertEqual(call[6], "20261029T210000Z")
        self.assertEqual(call[10:12], ("fitment_request", "review"))

    def test_counter_failure_does_not_fail_customer_submission(self):
        with patch("notifications.lead_digest._backend", side_effect=ConnectionError("unavailable")):
            with self.assertLogs("notifications.lead_digest", level="WARNING"):
                self.assertFalse(lead_digest.queue_lead_digest(form_type="fitment_request", suspicious=True))

    def test_outage_warning_is_throttled_and_does_not_expose_connection_text(self):
        with patch("notifications.lead_digest._backend", side_effect=ConnectionError("redis://secret:password@host")):
            with self.assertLogs("notifications.lead_digest", level="WARNING") as logs:
                for _ in range(5):
                    self.assertFalse(lead_digest.queue_lead_digest(form_type="fitment_request", suspicious=True))
        self.assertEqual(len(logs.output), 1)
        self.assertNotIn("password", logs.output[0])

    def test_report_separates_saved_customer_requests_from_blocked_attempts(self):
        report = lead_digest._report(
            {
                "count:fitment_request:review": "2",
                "count:fitment_request:blocked": "5",
                "count:service_lead:review": "1",
            },
            self.local(2026, 11, 2, 21),
        )
        self.assertIn("Saved for review: 3", report)
        self.assertIn("Blocked attempts: 5", report)
        self.assertIn("Fitment requests: 2 for review, 5 blocked", report)
        self.assertIn("Service requests: 1 for review", report)
        self.assertIn("Nov 02 15:00 – Nov 02 21:00", report)
        self.assertNotIn("New:", report)
        self.assertNotIn("Window: 0", report)

    def _scheduled_send(self, *, durable_count):
        self.client.zrangebyscore.return_value = [b"20261103T040000Z"]
        self.client.eval.return_value = [b"count:fitment_request:review", b"2", b"total", b"2"]
        settings_obj = SimpleNamespace(chat_id_list=[111, 222, 111])
        return (
            patch("notifications.models.TelegramBotSettings.load_active", return_value=settings_obj),
            patch("notifications.delivery.queued_message_count", return_value=durable_count),
            patch("notifications.services.send_telegram_message", return_value=0),
        )

    def test_partial_durable_handoff_retains_snapshot_and_reuses_same_key(self):
        settings_patch, count_patch, send_patch = self._scheduled_send(durable_count=1)
        with settings_patch, count_patch, send_patch as send:
            lead_digest.send_due_lead_digest(self.local(2026, 11, 2, 21, 1))
            lead_digest.send_due_lead_digest(self.local(2026, 11, 2, 21, 2))
        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args_list[0].kwargs["dedupe_key"], "lead-digest:20261103T040000Z")
        self.assertEqual(send.call_args_list[0].kwargs["chat_ids"], [111, 222])
        self.assertEqual(send.call_args_list[0].kwargs, send.call_args_list[1].kwargs)
        self.assertFalse(any(call.args[0] == lead_digest.ACK_SCRIPT for call in self.client.eval.call_args_list))

    def test_durable_failed_sends_are_handed_off_without_waiting_for_telegram(self):
        settings_patch, count_patch, send_patch = self._scheduled_send(durable_count=2)
        with settings_patch, count_patch, send_patch:
            # Zero HTTP successes can still mean both retryable outbox records
            # exist. Keeping the Redis snapshot would be redundant work.
            result = lead_digest.send_due_lead_digest(self.local(2026, 11, 2, 21, 1))
        self.assertEqual(result, 0)
        self.assertEqual(self.client.eval.call_args.args[0], lead_digest.ACK_SCRIPT)

    def test_no_future_window_is_sent_before_due_time(self):
        self.client.zrangebyscore.return_value = []
        now = self.local(2026, 11, 2, 20, 59)
        with patch("notifications.models.TelegramBotSettings.load_active", return_value=SimpleNamespace(chat_id_list=[111])):
            self.assertEqual(lead_digest.send_due_lead_digest(now), 0)
            self.assertEqual(lead_digest.send_due_lead_digest(now, force=True), 0)
        self.assertEqual(self.client.zrangebyscore.call_args.args[2], now.timestamp())
        self.client.eval.assert_not_called()

    def test_disabled_bot_keeps_counters_for_later(self):
        with patch("notifications.models.TelegramBotSettings.load_active", return_value=None):
            self.assertEqual(lead_digest.send_due_lead_digest(), 0)
        self.client.zrangebyscore.assert_not_called()


@skipUnless(os.environ.get("LEAD_DIGEST_TEST_REDIS_URL"), "Set LEAD_DIGEST_TEST_REDIS_URL for Redis concurrency checks")
class LeadDigestRedisIntegrationTests(SimpleTestCase):
    """Exercise the real Lua transactions in an isolated, cleaned-up namespace."""

    def setUp(self):
        import redis

        self.client = redis.Redis.from_url(os.environ["LEAD_DIGEST_TEST_REDIS_URL"])
        self.namespace = "bgm-digest-test:" + uuid.uuid4().hex
        self.make_key = lambda key: f"{self.namespace}:{key}"
        self.client.ping()
        self.addCleanup(self.cleanup_redis)
        backend_patch = patch("notifications.lead_digest._backend", return_value=(self.client, self.make_key))
        backend_patch.start()
        self.addCleanup(backend_patch.stop)
        self.now = timezone.make_aware(datetime(2026, 10, 28, 20, 59))

    def cleanup_redis(self):
        keys = list(self.client.scan_iter(match=f"{self.namespace}:*"))
        if keys:
            self.client.delete(*keys)
        self.client.close()

    def test_parallel_producers_keep_all_counts_and_bound_ip_memory(self):
        def submit(index):
            lead_digest.queue_lead_digest(
                form_type="fitment_request", suspicious=True,
                ip_address=f"192.0.2.{index}",
            )

        with patch("notifications.lead_digest.timezone.now", return_value=self.now):
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(submit, range(100)))
        end = lead_digest._slot_end(self.now)
        live, _, _ = lead_digest._keys(self.make_key, lead_digest._slot_key(end))
        state = lead_digest._decode_hash(self.client.hgetall(live))
        self.assertEqual(int(state["total"]), 100)
        self.assertEqual(int(state["count:fitment_request:blocked"]), 100)
        self.assertEqual(len([key for key in state if key.startswith("ip:")]), 25)

    def test_late_producer_cannot_modify_or_be_deleted_with_sealed_snapshot(self):
        with patch("notifications.lead_digest.timezone.now", return_value=self.now):
            lead_digest.queue_lead_digest(form_type="fitment_request", suspicious=True)
        end = lead_digest._slot_end(self.now)
        slot = lead_digest._slot_key(end)
        live, snapshot, sealed = lead_digest._keys(self.make_key, slot)
        index = self.make_key("tg:lead-digest:v2:windows")
        self.client.eval(lead_digest.SEAL_SCRIPT, 4, live, snapshot, sealed, index, slot)

        # A request that calculated its bucket just before the boundary can
        # finish after sealing. Its event must survive snapshot cleanup.
        with patch("notifications.lead_digest.timezone.now", return_value=self.now):
            lead_digest.queue_lead_digest(form_type="fitment_request", suspicious=True)
        self.assertEqual(self.client.hget(snapshot, "total"), b"1")
        self.client.eval(lead_digest.ACK_SCRIPT, 2, snapshot, index, slot)
        next_end = lead_digest._slot_end(end + timedelta(seconds=1))
        next_live, _, _ = lead_digest._keys(self.make_key, lead_digest._slot_key(next_end))
        self.assertEqual(self.client.hget(next_live, "total"), b"1")
