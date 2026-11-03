from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase
from django.db import connection
from django.utils import timezone
from telebot.apihelper import ApiTelegramException

from notifications.delivery import (
    _deliver,
    is_message_queued,
    process_pending_messages,
    queued_message_count,
    send_message,
)
from notifications.models import TelegramBotSettings, TelegramMessageLog


class ReliableTelegramDeliveryTests(TestCase):
    def setUp(self):
        self.settings = TelegramBotSettings.objects.create(
            enabled=True,
            bot_token="123456:test-token",
            admin_chat_ids="101, 202 101",
        )
        self.bot = Mock()
        self.bot.send_message.return_value = SimpleNamespace(message_id=321)
        self.bot_factory = patch("notifications.services.build_bot", return_value=(self.bot, self.settings))
        self.bot_factory.start()
        self.addCleanup(self.bot_factory.stop)

    def test_reserves_all_recipients_before_network_and_deduplicates(self):
        def send(*args, **kwargs):
            self.assertEqual(TelegramMessageLog.objects.count(), 2)
            return SimpleNamespace(message_id=321)

        self.bot.send_message.side_effect = send
        self.assertEqual(send_message("Useful lead", event_type="fitment_request", dedupe_key="fitment:1"), 2)
        self.assertEqual(self.bot.send_message.call_count, 2)
        self.assertEqual(queued_message_count("fitment:1", [101, 202, 101]), 2)
        self.assertTrue(is_message_queued("fitment:1", [101, 202]))

    def test_repeated_entity_key_does_not_send_again(self):
        kwargs = dict(event_type="fitment_request", dedupe_key="fitment:7", entity_type="fitment_request", entity_id=7)
        self.assertEqual(send_message("Original payload", **kwargs), 2)
        self.assertEqual(send_message("Repeated form request", **kwargs), 0)
        self.assertEqual(self.bot.send_message.call_count, 2)
        self.assertEqual(TelegramMessageLog.objects.count(), 2)
        row = TelegramMessageLog.objects.get(chat_id=101)
        self.assertEqual(row.payload, "Original payload")
        self.assertEqual(row.entity_id, "7")
        self.assertEqual(row.telegram_message_id, 321)
        self.assertEqual(row.status, TelegramMessageLog.Status.SENT)
        self.assertTrue(row.success)
        self.assertIsNotNone(row.sent_at)

    def test_partial_failure_retries_only_failed_recipient(self):
        self.bot.send_message.side_effect = [SimpleNamespace(message_id=1), TimeoutError("Telegram timed out")]
        self.assertEqual(send_message("Lead", event_type="fitment_request", dedupe_key="fitment:8"), 1)
        failed = TelegramMessageLog.objects.get(chat_id=202)
        self.assertEqual(failed.status, TelegramMessageLog.Status.UNCERTAIN)
        self.assertEqual(failed.attempts, 1)
        self.assertIsNotNone(failed.next_attempt_at)
        self.assertEqual(process_pending_messages(), 0)
        TelegramMessageLog.objects.filter(pk=failed.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        self.bot.send_message.reset_mock()
        self.bot.send_message.side_effect = None
        self.assertEqual(process_pending_messages(), 1)
        self.bot.send_message.assert_called_once()
        self.assertEqual(self.bot.send_message.call_args.args[0], 202)
        failed.refresh_from_db()
        self.assertEqual(failed.status, TelegramMessageLog.Status.SENT)
        self.assertEqual(failed.attempts, 2)

    def test_disabled_bot_keeps_pending_message_for_later(self):
        self.settings.enabled = False
        self.settings.save(update_fields=["enabled"])
        self.assertEqual(send_message("Lead", event_type="fitment_request", dedupe_key="fitment:9"), 0)
        self.assertEqual(TelegramMessageLog.objects.filter(status="pending").count(), 2)
        self.bot.send_message.assert_not_called()
        self.assertEqual(process_pending_messages(), 0)
        self.settings.enabled = True
        self.settings.save(update_fields=["enabled"])
        self.assertEqual(process_pending_messages(), 2)

    def test_active_claim_blocks_competing_sender_and_stale_claim_recovers(self):
        row = TelegramMessageLog.objects.create(
            chat_id=101,
            event_type="fitment_request",
            payload="Lead",
            success=False,
            status="sending",
            claimed_at=timezone.now(),
            attempts=1,
        )
        self.assertFalse(_deliver(row, self.bot))
        self.bot.send_message.assert_not_called()
        TelegramMessageLog.objects.filter(pk=row.pk).update(claimed_at=timezone.now() - timedelta(minutes=4))
        self.assertTrue(_deliver(row, self.bot))
        self.assertFalse(_deliver(row, self.bot))
        self.bot.send_message.assert_called_once()

    def test_historical_failure_is_not_replayed_without_explicit_retry(self):
        TelegramMessageLog.objects.create(
            chat_id=101, event_type="appointment_created", payload="Old failure", success=False, status="failed",
        )
        self.assertEqual(process_pending_messages(), 0)
        self.bot.send_message.assert_not_called()

    def test_errors_do_not_expose_bot_token(self):
        self.bot.send_message.side_effect = TimeoutError("https://api.telegram.org/bot123456:test-token/sendMessage")
        send_message("Lead", event_type="fitment_request", chat_ids=[101])
        row = TelegramMessageLog.objects.get()
        self.assertNotIn(self.settings.bot_token, row.error_message)
        self.assertIn("redacted", row.error_message)

    def test_explicit_empty_recipient_list_does_not_fall_back_to_admins(self):
        self.assertEqual(send_message("Private message", event_type="manual", chat_ids=[]), 0)
        self.assertEqual(TelegramMessageLog.objects.count(), 0)
        self.bot.send_message.assert_not_called()

    def test_telegram_rate_limit_preserves_record_and_respects_retry_after(self):
        self.bot.send_message.side_effect = ApiTelegramException(
            "sendMessage", None,
            {"error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 600}},
        )
        before = timezone.now()
        self.assertEqual(send_message("Lead", event_type="fitment_request", chat_ids=[101]), 0)
        row = TelegramMessageLog.objects.get()
        self.assertEqual(row.status, TelegramMessageLog.Status.FAILED)
        self.assertGreaterEqual(row.next_attempt_at, before + timedelta(seconds=600))
        self.assertEqual(row.payload, "Lead")

    def test_retry_batch_is_bounded(self):
        for chat_id in [101, 202, 303]:
            TelegramMessageLog.objects.create(
                chat_id=chat_id, event_type="fitment_request", payload="Lead", success=False, status="pending",
            )
        self.assertEqual(process_pending_messages(limit=1), 1)
        self.assertEqual(self.bot.send_message.call_count, 1)
        self.assertEqual(TelegramMessageLog.objects.filter(status="pending").count(), 2)

    def test_old_release_can_insert_legacy_log_columns_during_rolling_deploy(self):
        # The old running containers do not know the added non-null columns.
        # Persistent SQL defaults keep their INSERTs valid during migration and
        # also make rolling back the application safe without dropping data.
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO notifications_telegrammessagelog "
                "(event_type, chat_id, payload, success, error_message, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                ["fitment_request", 101, "Legacy release notification", True, "", timezone.now()],
            )
            row_id = cursor.fetchone()[0]
        row = TelegramMessageLog.objects.get(pk=row_id)
        self.assertEqual(row.status, TelegramMessageLog.Status.SENT)
        self.assertEqual(row.entity_type, "")
        self.assertEqual(row.entity_id, "")
        self.assertEqual(row.digest_slot, "")
        self.assertEqual(row.attempts, 0)
        self.assertIsNone(row.dedupe_key)
