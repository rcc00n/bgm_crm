from __future__ import annotations

import csv
import io
import sys
import base64
import gzip
from collections import Counter
from email.utils import parseaddr

from django.core.management.base import BaseCommand
from django.core.validators import validate_email
from django.utils import timezone

from core.models import EmailSubscriber


EMAIL_SPLIT_CHARS = ",; \t\r\n"


def _normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def _split_emailish(value: str) -> list[str]:
    """Split a cell value that may contain one or more emails."""
    if not value:
        return []
    # Fast path: no split chars except maybe in a display name.
    value = value.strip()
    if not value:
        return []

    parts: list[str] = []
    buf: list[str] = []
    for ch in value:
        if ch in EMAIL_SPLIT_CHARS:
            if buf:
                parts.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _extract_emails_from_row(row: dict[str, str]) -> tuple[list[str], int]:
    """
    Return (emails, invalid_count) for a CSV row by scanning all fields.
    """
    emails: list[str] = []
    invalid = 0
    for raw in (row or {}).values():
        cell = str(raw or "").strip()
        if not cell or "@" not in cell:
            continue

        candidates: list[str] = []
        _name, addr = parseaddr(cell)
        if addr and "@" in addr:
            candidates.append(addr)
        for token in _split_emailish(cell):
            if "@" in token:
                candidates.append(token.strip("<>\"'()[]{}"))

        for candidate in candidates:
            candidate = _normalize_email(candidate)
            if not candidate or "@" not in candidate:
                continue
            try:
                validate_email(candidate)
            except Exception:
                invalid += 1
                continue
            emails.append(candidate)
    # Keep stable order but unique per row.
    seen = set()
    unique: list[str] = []
    for e in emails:
        if e in seen:
            continue
        seen.add(e)
        unique.append(e)
    return unique, invalid


def _status_to_active(status: str) -> bool:
    """
    Map the "Статус подписчика на рассылку" export column to EmailSubscriber.is_active.
    Defaults to inactive unless the row explicitly says the contact is subscribed.
    """
    s = (status or "").strip().lower()
    if not s:
        return False
    subscribed_tokens = {
        "подписчик",
        "subscribed",
        "subscriber",
    }
    unsubscribed_tokens = {
        "контакт отписался",
        "отпис",
        "unsubscribed",
        "unsub",
    }
    if s in subscribed_tokens:
        return True
    if s in unsubscribed_tokens:
        return False
    # "Не подписывался(лась)" and any other unknown value -> inactive
    return False


def _merge_active(existing: bool | None, new_value: bool) -> bool:
    """
    Merge multiple statuses for the same email (if it appears more than once).
    Inactive wins (once unsubscribed, keep inactive).
    """
    if existing is None:
        return new_value
    if existing is False:
        return False
    return bool(new_value)


def _read_contacts_csv(fp: io.TextIOBase) -> tuple[dict[str, bool], Counter, int]:
    """
    Returns (email_to_active, status_counts, invalid_count)
    """
    reader = csv.DictReader(fp)
    status_col = "Статус подписчика на рассылку"

    email_to_active: dict[str, bool] = {}
    status_counts: Counter = Counter()
    invalid_count = 0

    for row in reader:
        status = (row.get(status_col) or "").strip() or "(blank)"
        status_counts[status] += 1
        desired_active = _status_to_active(status)

        row_emails, row_invalid = _extract_emails_from_row(row)
        invalid_count += row_invalid
        for email in row_emails:
            email_to_active[email] = _merge_active(email_to_active.get(email), desired_active)

    return email_to_active, status_counts, invalid_count


class Command(BaseCommand):
    help = "Import a contacts export CSV into EmailSubscriber, updating is_active based on subscriber status."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default=None,
            help="Path to a contacts CSV export. If omitted, use --stdin.",
        )
        parser.add_argument(
            "--stdin",
            action="store_true",
            help="Read CSV content from stdin.",
        )
        parser.add_argument(
            "--gz-base64",
            dest="gz_base64",
            default=None,
            help="Base64-encoded *gzipped* CSV payload (avoids stdin/tty issues on some hosts).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply changes to the database. Without this flag, runs as a dry-run.",
        )

    def handle(self, *args, **options):
        path = options.get("path")
        use_stdin = bool(options.get("stdin"))
        gz_base64 = options.get("gz_base64")
        apply_changes = bool(options.get("apply"))

        sources = [bool(path), use_stdin, bool(gz_base64)]
        if sum(1 for x in sources if x) != 1:
            raise SystemExit("Provide exactly one input source: --path, --stdin, or --gz-base64.")

        if gz_base64:
            raw = base64.b64decode(gz_base64.encode("utf-8"), validate=False)
            text = gzip.decompress(raw).decode("utf-8-sig", errors="ignore")
            fp = io.StringIO(text)
        elif use_stdin:
            data = sys.stdin.buffer.read()
            text = data.decode("utf-8-sig", errors="ignore")
            fp = io.StringIO(text)
        else:
            fp = open(path, "r", encoding="utf-8-sig", newline="")

        try:
            email_to_active, status_counts, invalid_count = _read_contacts_csv(fp)
        finally:
            fp.close()

        emails = sorted(email_to_active.keys())
        total_emails = len(emails)

        self.stdout.write(f"Parsed {total_emails} unique email(s).")
        if status_counts:
            self.stdout.write("Status rows:")
            for status, count in status_counts.most_common():
                self.stdout.write(f"  {status}: {count}")
        if invalid_count:
            self.stdout.write(self.style.WARNING(f"Invalid email value(s) skipped: {invalid_count}"))

        if total_emails == 0:
            return

        existing = EmailSubscriber.objects.filter(email__in=emails)
        existing_map = {s.email: s for s in existing}

        to_create = []
        to_activate: list[str] = []
        to_deactivate: list[str] = []
        unchanged = 0

        for email in emails:
            desired_active = email_to_active[email]
            current = existing_map.get(email)
            if current is None:
                to_create.append(
                    EmailSubscriber(
                        email=email,
                        source=EmailSubscriber.Source.IMPORT,
                        is_active=desired_active,
                    )
                )
                continue
            if bool(current.is_active) == bool(desired_active):
                unchanged += 1
                continue
            if desired_active:
                to_activate.append(email)
            else:
                to_deactivate.append(email)

        self.stdout.write("")
        self.stdout.write("Plan:")
        self.stdout.write(f"  Create: {len(to_create)}")
        self.stdout.write(f"  Activate: {len(to_activate)}")
        self.stdout.write(f"  Deactivate: {len(to_deactivate)}")
        self.stdout.write(f"  Unchanged: {unchanged}")

        if not apply_changes:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --apply to write changes."))
            return

        now = timezone.now()
        created_count = 0
        if to_create:
            EmailSubscriber.objects.bulk_create(to_create, ignore_conflicts=True)
            created_count = len(to_create)

        activated_count = 0
        if to_activate:
            activated_count = EmailSubscriber.objects.filter(email__in=to_activate).update(
                is_active=True,
                updated_at=now,
            )

        deactivated_count = 0
        if to_deactivate:
            deactivated_count = EmailSubscriber.objects.filter(email__in=to_deactivate).update(
                is_active=False,
                updated_at=now,
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Done."))
        self.stdout.write(f"  Created: {created_count}")
        self.stdout.write(f"  Activated: {activated_count}")
        self.stdout.write(f"  Deactivated: {deactivated_count}")
