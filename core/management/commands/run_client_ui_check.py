from django.core.management.base import BaseCommand

from core.services.ui_audit import run_client_ui_check
from core.models import ClientUiCheckRun


class Command(BaseCommand):
    help = "Runs the client UI audit and sends the Telegram report."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run immediately, ignoring the 3-day schedule.",
        )
        parser.add_argument(
            "--no-telegram",
            action="store_true",
            help="Skip sending the Telegram report.",
        )

    def handle(self, *args, **options):
        run = run_client_ui_check(
            trigger=ClientUiCheckRun.Trigger.AUTO,
            force=options["force"],
            send_telegram=not options["no_telegram"],
        )

        if not run:
            self.stdout.write("UI check skipped (not due yet).")
            return

        if run.status == ClientUiCheckRun.Status.RUNNING:
            self.stdout.write("UI check already running.")
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"UI check finished: {run.get_status_display()} "
                f"(failures {run.failures_count}, warnings {run.warnings_count})."
            )
        )
