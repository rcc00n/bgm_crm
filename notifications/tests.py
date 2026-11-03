from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

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


class TelegramReminderAdminTests(TestCase):
    def setUp(self):
        self.superuser = get_user_model().objects.create_superuser(
            username="telegram-admin",
            email="telegram-admin@example.com",
            password="StrongPass123!",
        )
        self.client.force_login(self.superuser)

    @patch("notifications.admin.services.deliver_reminder", return_value=2)
    def test_admin_add_sends_due_reminder_on_save(self, deliver_mock):
        due_local = timezone.localtime(timezone.now() - timedelta(minutes=1))
        response = self.client.post(
            reverse("admin:notifications_telegramreminder_add"),
            data={
                "title": "Admin update",
                "message": "Panel refreshed.",
                "scheduled_for_0": due_local.date().isoformat(),
                "scheduled_for_1": due_local.strftime("%H:%M:%S"),
                "status": TelegramReminder.Status.PENDING,
                "target_chat_ids": "",
                "_save": "Save",
            },
            secure=True,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        reminder = TelegramReminder.objects.get(title="Admin update")
        deliver_mock.assert_called_once_with(reminder)
        self.assertContains(response, "Reminder sent to 2 Telegram recipient(s).")

    @patch("notifications.admin.services.deliver_reminder")
    def test_admin_change_does_not_resend_when_reminder_already_sent(self, deliver_mock):
        reminder = TelegramReminder.objects.create(
            title="Already sent",
            message="Done",
            scheduled_for=timezone.now() - timedelta(minutes=1),
            status=TelegramReminder.Status.SENT,
            sent_at=timezone.now(),
        )

        response = self.client.post(
            reverse("admin:notifications_telegramreminder_change", args=[reminder.pk]),
            data={
                "title": reminder.title,
                "message": reminder.message,
                "scheduled_for_0": timezone.localdate().isoformat(),
                "scheduled_for_1": "12:05:00",
                "status": TelegramReminder.Status.SENT,
                "target_chat_ids": "",
                "_save": "Save",
            },
            secure=True,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        deliver_mock.assert_not_called()


    @patch("notifications.admin.services.deliver_reminder")
    def test_admin_add_preserves_future_schedule(self, deliver_mock):
        future = timezone.localtime(timezone.now() + timedelta(days=1))
        response = self.client.post(
            reverse("admin:notifications_telegramreminder_add"),
            data={
                "title": "Tomorrow",
                "message": "Scheduled customer follow-up.",
                "scheduled_for_0": future.date().isoformat(),
                "scheduled_for_1": future.strftime("%H:%M:%S"),
                "status": TelegramReminder.Status.PENDING,
                "target_chat_ids": "",
                "_save": "Save",
            },
            secure=True,
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        reminder = TelegramReminder.objects.get(title="Tomorrow")
        self.assertGreater(reminder.scheduled_for, timezone.now())
        self.assertEqual(reminder.status, TelegramReminder.Status.PENDING)
        deliver_mock.assert_not_called()
        self.assertContains(response, "Reminder scheduled")


class SafeTelegramTextTests(SimpleTestCase):
    def test_campaign_domains_are_neutralized_and_html_escaped(self):
        from notifications.services import safe_user_text

        rendered = safe_user_text('<script> https://files.partagepro.online/en/project')
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("files[.]partagepro[.]online", rendered)
        self.assertNotIn("partagepro.online", rendered)

    def test_normal_customer_urls_and_unrelated_domains_remain_readable(self):
        from notifications.services import safe_user_text

        value = "https://drive.google.com/customer-photo https://partagepro.online.example.com/legitimate"
        self.assertEqual(safe_user_text(value), value)

    def test_long_escaped_text_and_emoji_respect_budget_without_cutting_entities(self):
        from notifications.services import safe_user_text

        rendered = safe_user_text("&" * 10000, max_length=1600)
        self.assertLessEqual(len(rendered), 1600)
        self.assertTrue(rendered.endswith("…"))
        self.assertNotIn("&am…", rendered)
        emoji = safe_user_text("🚚" * 3000, max_length=1600)
        self.assertLessEqual(len(emoji.encode("utf-16-le")) // 2, 1600)


class ScheduledTelegramDeliveryTests(TestCase):
    def setUp(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        self.settings = TelegramBotSettings.objects.create(
            enabled=True, bot_token="123456:test", admin_chat_ids="101, 202", digest_enabled=True, digest_hour_local=0,
        )
        self.bot = Mock()
        self.bot.send_message.return_value = SimpleNamespace(message_id=123)
        self.factory = patch("notifications.services.build_bot", return_value=(self.bot, self.settings))
        self.factory.start()
        self.addCleanup(self.factory.stop)

    @patch("notifications.services.build_operations_digest", return_value="Daily operations")
    def test_daily_digest_is_deduplicated_across_stale_settings(self, build_mock):
        from notifications.services import send_daily_digest
        from notifications.models import TelegramMessageLog

        self.assertEqual(send_daily_digest(), 2)
        # Simulate another scheduler observing stale singleton date state.
        TelegramBotSettings.objects.filter(pk=self.settings.pk).update(last_digest_sent_on=None)
        self.assertEqual(send_daily_digest(), 0)
        self.assertEqual(self.bot.send_message.call_count, 2)
        self.assertEqual(TelegramMessageLog.objects.count(), 2)

    def test_reminder_retains_pending_state_until_all_recipients_succeed(self):
        from types import SimpleNamespace
        from notifications.delivery import process_pending_messages
        from notifications.models import TelegramMessageLog
        from notifications.services import deliver_reminder

        reminder = TelegramReminder.objects.create(title="Follow-up", message="Customer call")
        self.bot.send_message.side_effect = [SimpleNamespace(message_id=1), TimeoutError("timeout")]
        self.assertEqual(deliver_reminder(reminder), 1)
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, TelegramReminder.Status.PENDING)
        TelegramMessageLog.objects.filter(status="uncertain").update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        self.bot.send_message.side_effect = None
        self.assertEqual(process_pending_messages(), 1)
        self.assertEqual(deliver_reminder(reminder), 0)
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, TelegramReminder.Status.SENT)
        self.assertEqual(self.bot.send_message.call_count, 3)

    @patch("notifications.services.deliver_reminder")
    def test_automatic_reminders_exclude_legacy_pending_items_before_cutover(self, deliver_mock):
        from notifications.services import process_due_reminders

        cutover = timezone.now() - timedelta(hours=1)
        TelegramReminder.objects.create(title="Legacy", message="Old", scheduled_for=cutover - timedelta(days=365))
        due = TelegramReminder.objects.create(title="Current", message="Due", scheduled_for=cutover + timedelta(minutes=1))
        self.assertEqual(process_due_reminders(since=cutover), 1)
        deliver_mock.assert_called_once_with(due)

    @patch("notifications.services.send_staff_email_notification", return_value=1)
    def test_long_customer_message_is_preserved_with_bounded_telegram_and_admin_link(self, email_mock):
        from notifications.models import TelegramMessageLog
        from notifications.services import notify_about_fitment_request
        from store.models import CustomFitmentRequest

        original_message = "Truck details & photos " * 1000
        request = CustomFitmentRequest.objects.create(
            customer_name="Real customer", email="customer@example.com", message=original_message,
        )
        self.assertEqual(notify_about_fitment_request(request.pk), 2)
        request.refresh_from_db()
        self.assertEqual(request.message, original_message)
        payload = TelegramMessageLog.objects.first().payload
        self.assertLessEqual(len(payload.encode("utf-16-le")) // 2, 4096)
        self.assertIn(f"/admin/store/customfitmentrequest/{request.pk}/change/", payload)
        self.assertIn("…", payload)
