from django.test import SimpleTestCase, TestCase

from notifications.models import TelegramBotSettings, TelegramRecipientSlot, _parse_id_list


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
