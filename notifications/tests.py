from datetime import datetime, timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from notifications.services import queue_lead_digest
from notifications.models import (
    TelegramBotSettings,
    TelegramContact,
    TelegramRecipientSlot,
    TelegramReminder,
    _parse_id_list,
)


class ParseIdListTests(SimpleTestCase):
    def test_parses_ids_from_mixed_separators(self):
        self.assertEqual(_parse_id_list("123, 456 789"), [123, 456, 789])

    def test_ignores_invalid_tokens(self):
        self.assertEqual(_parse_id_list("123, abc, 456"), [123, 456])

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(_parse_id_list(""), [])


class TelegramBotSettingsTests(TestCase):
    def test_chat_id_list_prefers_slots_and_dedupes_legacy(self):
        settings = TelegramBotSettings.objects.create(
            admin_chat_ids="111, 222",
            enabled=True,
            bot_token="token",
        )
        TelegramRecipientSlot.objects.create(settings=settings, chat_id=222)
        TelegramRecipientSlot.objects.create(settings=settings, chat_id=333)

        self.assertEqual(settings.chat_id_list, [222, 333, 111])

    def test_is_ready_requires_enabled_token_and_chat_ids(self):
        settings = TelegramBotSettings.objects.create(
            admin_chat_ids="",
            enabled=True,
            bot_token="token",
        )
        self.assertFalse(settings.is_ready)

        settings.admin_chat_ids = "999"
        settings.save(update_fields=["admin_chat_ids"])
        self.assertTrue(settings.is_ready)

    def test_allowed_user_id_list_prefers_explicit_ids(self):
        settings = TelegramBotSettings.objects.create(
            admin_chat_ids="111",
            allowed_user_ids="222 333",
            enabled=True,
            bot_token="token",
        )
        self.assertEqual(settings.allowed_user_id_list, [222, 333])

    def test_allowed_user_id_list_falls_back_to_chat_ids(self):
        settings = TelegramBotSettings.objects.create(
            admin_chat_ids="111",
            enabled=True,
            bot_token="token",
        )
        self.assertEqual(settings.allowed_user_id_list, [111])

    def test_load_active_returns_ready_settings(self):
        settings = TelegramBotSettings.objects.create(
            admin_chat_ids="111",
            enabled=True,
            bot_token="token",
        )
        self.assertEqual(TelegramBotSettings.load_active(), settings)

    def test_slot_chat_ids_empty_for_unsaved_instance(self):
        self.assertEqual(TelegramBotSettings().slot_chat_ids, [])


class TelegramReminderTests(TestCase):
    def test_chat_id_list_combines_contacts_and_manual_ids(self):
        contact_a = TelegramContact.objects.create(name="Alpha", chat_id=100)
        contact_b = TelegramContact.objects.create(name="Zulu", chat_id=200)
        reminder = TelegramReminder.objects.create(
            title="Follow up",
            message="Ping",
            target_chat_ids="200 300",
        )
        reminder.contacts.add(contact_a, contact_b)

        self.assertEqual(reminder.chat_id_list, [100, 200, 300])

    def test_mark_sent_updates_status_and_timestamp(self):
        reminder = TelegramReminder.objects.create(title="Ping", message="Hello")
        reminder.mark_sent(success=True)
        reminder.refresh_from_db()

        self.assertEqual(reminder.status, TelegramReminder.Status.SENT)
        self.assertIsNotNone(reminder.sent_at)
        self.assertEqual(reminder.last_error, "")

    def test_clean_rejects_old_pending_reminders(self):
        reminder = TelegramReminder(
            title="Old",
            message="Hello",
            scheduled_for=timezone.now() - timedelta(days=31),
        )
        with self.assertRaises(ValidationError):
            reminder.full_clean()

    def test_due_returns_pending_reminders_ready_to_send(self):
        due = TelegramReminder.objects.create(
            title="Due",
            message="Ready",
            scheduled_for=timezone.now() - timedelta(minutes=5),
        )
        TelegramReminder.objects.create(
            title="Future",
            message="Later",
            scheduled_for=timezone.now() + timedelta(days=1),
        )
        TelegramReminder.objects.create(
            title="Sent",
            message="Done",
            scheduled_for=timezone.now() - timedelta(minutes=5),
            status=TelegramReminder.Status.SENT,
        )

        self.assertEqual(list(TelegramReminder.due()), [due])


class LeadDigestScheduleTests(TestCase):
    def setUp(self):
        cache.clear()

    def _dt(self, year, month, day, hour, minute=0):
        tz = timezone.get_default_timezone()
        return timezone.make_aware(datetime(year, month, day, hour, minute), tz)

    @patch("notifications.services.send_telegram_message")
    @patch("notifications.services.timezone.now")
    def test_digest_only_sends_on_scheduled_slots(self, mock_now, mock_send):
        mock_now.side_effect = [
            self._dt(2026, 1, 30, 14, 0),
            self._dt(2026, 1, 30, 15, 5),
            self._dt(2026, 1, 30, 15, 10),
            self._dt(2026, 1, 30, 21, 1),
        ]

        queue_lead_digest(
            form_type="site_notice",
            suspicious=True,
            ip_address="1.2.3.4",
            asn="AS100",
        )
        self.assertEqual(mock_send.call_count, 0)

        queue_lead_digest(
            form_type="site_notice",
            suspicious=True,
            ip_address="1.2.3.5",
            asn="AS100",
        )
        self.assertEqual(mock_send.call_count, 1)

        queue_lead_digest(
            form_type="site_notice",
            suspicious=True,
            ip_address="1.2.3.6",
            asn="AS200",
        )
        self.assertEqual(mock_send.call_count, 1)

        queue_lead_digest(
            form_type="site_notice",
            suspicious=True,
            ip_address="1.2.3.7",
            asn="AS200",
        )
        self.assertEqual(mock_send.call_count, 2)
