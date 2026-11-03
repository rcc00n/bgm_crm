from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from notifications import automation


class TelegramAutomationTests(SimpleTestCase):
    @patch("notifications.automation.close_old_connections")
    @patch("notifications.services.process_due_reminders")
    @patch("notifications.services.send_daily_digest")
    @patch("notifications.lead_digest.send_due_lead_digest")
    @patch("notifications.delivery.process_pending_messages")
    def test_one_failing_task_does_not_starve_other_notifications(
        self, pending, lead_digest, daily_digest, reminders, close_connections,
    ):
        pending.__name__ = "process_pending_messages"
        pending.side_effect = RuntimeError("Temporary Telegram failure")
        with self.assertLogs("notifications.automation", level="ERROR"):
            automation.run_once()
        pending.assert_called_once_with(limit=5)
        lead_digest.assert_called_once_with()
        daily_digest.assert_called_once_with()
        reminders.assert_called_once_with(limit=5)
        self.assertEqual(close_connections.call_count, 8)

    @patch("notifications.automation.threading.Thread")
    @patch("notifications.automation.run_once")
    def test_scheduler_waits_between_ticks_and_stops_without_another_run(self, run_once, thread):
        stop = Mock()
        stop.is_set.side_effect = [False, True]
        automation.start_scheduler(stop)
        target = thread.call_args.kwargs["target"]
        target()
        run_once.assert_called_once_with()
        stop.wait.assert_called_once_with(60)
