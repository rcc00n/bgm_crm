"""Persist outbound notifications before contacting Telegram and retry per recipient.

The database is a delivery journal, not the source of digest aggregation. Telegram
does not provide idempotency keys: a timeout after acceptance is ambiguous, and a
later retry can repeat that particular delivery. Such attempts remain explicit.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import timedelta
from typing import Sequence

from django.db.models import F, Q
from django.utils import timezone
from telebot.apihelper import ApiTelegramException

from .models import TelegramBotSettings, TelegramMessageLog

logger = logging.getLogger(__name__)
CLAIM_TIMEOUT = timedelta(minutes=3)
SEND_TIMEOUT_SECONDS = 10


def _normalise_key(value: str | None) -> str | None:
    if not value:
        return None
    value = str(value)
    return value if len(value) <= 255 else "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _recipients(settings_obj, chat_ids: Sequence[int] | None) -> list[int]:
    raw_ids = chat_ids if chat_ids is not None else (settings_obj.chat_id_list if settings_obj else [])
    return list(dict.fromkeys(int(chat_id) for chat_id in raw_ids))


def _safe_error(exc: Exception, token: str = "") -> str:
    text = f"{exc.__class__.__name__}: {exc}"
    if token:
        text = text.replace(token, "[redacted]")
    text = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot[redacted]", text)
    return text[:500]


def _claimable(now):
    due = Q(next_attempt_at__lte=now)
    # Only newly queued rows or explicit retries are sent. Historical failures
    # have no retry timestamp and must not be replayed after the migration.
    queued = Q(status=TelegramMessageLog.Status.PENDING) & (due | Q(next_attempt_at__isnull=True))
    retry = Q(status__in=[TelegramMessageLog.Status.FAILED, TelegramMessageLog.Status.UNCERTAIN]) & due
    abandoned = Q(status=TelegramMessageLog.Status.SENDING, claimed_at__lt=now - CLAIM_TIMEOUT)
    return queued | retry | abandoned


def _deliver(record: TelegramMessageLog, bot, *, token: str = "") -> bool:
    now = timezone.now()
    # UPDATE's predicate is rechecked under PostgreSQL's row lock. Competing web
    # workers and scheduler runs cannot both claim the same pending message.
    claimed = TelegramMessageLog.objects.filter(pk=record.pk).filter(_claimable(now)).update(
        status=TelegramMessageLog.Status.SENDING,
        success=False,
        claimed_at=now,
        next_attempt_at=None,
        attempts=F("attempts") + 1,
    )
    if not claimed:
        return False
    record.refresh_from_db(fields=["attempts"])
    try:
        sent = bot.send_message(
            record.chat_id,
            record.payload,
            disable_web_page_preview=True,
            timeout=SEND_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        # A Telegram error response is a definite failed API call; transport
        # failures can happen after Telegram accepted the message.
        definite_failure = isinstance(exc, ApiTelegramException)
        retry_seconds = min(6 * 60 * 60, 60 * (2 ** min(record.attempts - 1, 9)))
        if not definite_failure:
            retry_seconds = max(5 * 60, retry_seconds)
        response = (getattr(exc, "result_json", None) or {}) if definite_failure else {}
        retry_after = (response.get("parameters") or {}).get("retry_after")
        if isinstance(retry_after, (int, float)):
            retry_seconds = max(retry_seconds, int(retry_after) + 1)
        TelegramMessageLog.objects.filter(pk=record.pk).update(
            status=TelegramMessageLog.Status.FAILED if definite_failure else TelegramMessageLog.Status.UNCERTAIN,
            success=False,
            error_message=_safe_error(exc, token),
            claimed_at=None,
            next_attempt_at=timezone.now() + timedelta(seconds=retry_seconds),
        )
        logger.warning("Telegram delivery queued for retry: log_id=%s event=%s", record.pk, record.event_type)
        return False

    TelegramMessageLog.objects.filter(pk=record.pk).update(
        status=TelegramMessageLog.Status.SENT,
        success=True,
        error_message="",
        telegram_message_id=getattr(sent, "message_id", None),
        sent_at=timezone.now(),
        next_attempt_at=None,
        claimed_at=None,
    )
    return True


def send_message(
    message: str,
    *,
    event_type: str,
    chat_ids: Sequence[int] | None = None,
    dedupe_key: str | None = None,
    entity_type: str = "",
    entity_id: str = "",
    digest_slot: str = "",
) -> int:
    """Queue before sending; return the number newly delivered by this call."""
    settings_obj = TelegramBotSettings.load()
    recipients = _recipients(settings_obj, chat_ids)
    if not recipients:
        return 0
    key = _normalise_key(dedupe_key)
    records = []
    for chat_id in recipients:
        defaults = {
            "event_type": event_type,
            "payload": message,
            "success": False,
            "status": TelegramMessageLog.Status.PENDING,
            "entity_type": str(entity_type)[:64],
            "entity_id": str(entity_id)[:80],
            "digest_slot": str(digest_slot)[:64],
        }
        if key:
            record, _ = TelegramMessageLog.objects.get_or_create(chat_id=chat_id, dedupe_key=key, defaults=defaults)
        else:
            record = TelegramMessageLog.objects.create(chat_id=chat_id, **defaults)
        records.append(record)

    if not settings_obj or not settings_obj.is_ready:
        return 0
    # Imported lazily because services supplies the formatting and bot factory.
    from .services import build_bot

    bot, _ = build_bot(settings_obj)
    return sum(_deliver(record, bot, token=settings_obj.bot_token) for record in records)


def queued_message_count(dedupe_key: str, chat_ids: Sequence[int]) -> int:
    """Count expected recipients with a durable copy, regardless of HTTP result."""
    recipients = set(int(chat_id) for chat_id in chat_ids)
    if not recipients:
        return 0
    return TelegramMessageLog.objects.filter(
        dedupe_key=_normalise_key(dedupe_key), chat_id__in=recipients,
    ).count()


def is_message_queued(dedupe_key: str, chat_ids: Sequence[int]) -> bool:
    """True when every expected recipient has a durable copy of this payload."""
    recipients = set(int(chat_id) for chat_id in chat_ids)
    return bool(recipients) and queued_message_count(dedupe_key, chat_ids) == len(recipients)


def process_pending_messages(limit: int = 20) -> int:
    """Send a bounded batch; successful recipients are never selected again."""
    settings_obj = TelegramBotSettings.load_active()
    if not settings_obj:
        return 0
    from .services import build_bot

    bot, _ = build_bot(settings_obj)
    records = TelegramMessageLog.objects.filter(_claimable(timezone.now())).order_by("created_at")[:max(0, min(limit, 100))]
    return sum(_deliver(record, bot, token=settings_obj.bot_token) for record in records)
