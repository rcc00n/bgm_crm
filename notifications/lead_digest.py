"""Small shared lead counters; delivery runs in the existing bot process.

Redis stores counters, not customer inquiries. A closed window is renamed to an
immutable snapshot before it is sent. The snapshot is removed only after every
recipient has a durable delivery record; failed HTTP sends remain retryable in
the normal delivery queue.
"""
from __future__ import annotations

import html
import logging
import time
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.conf import settings
from django.core.cache import caches
from django.utils import timezone

logger = logging.getLogger(__name__)

HOURS_LOCAL = (15, 21)
FORM_LABELS = {
    "site_notice": "Site notice",
    "service_lead": "Service requests",
    "fitment_request": "Fitment requests",
    "store_review": "Store reviews",
    "lead": "Project requests",
}
_WARNING_LAST: dict[str, float] = {}


def _warn(message: str, exc: Exception) -> None:
    # A failed shared service must not turn a spam burst into a traceback burst.
    # Exception text can include connection credentials; log only its type.
    now = time.monotonic()
    if now - _WARNING_LAST.get(message, float("-inf")) >= 60:
        _WARNING_LAST[message] = now
        logger.warning("%s (%s)", message, type(exc).__name__)

# The queue operation is a single Redis transaction. The hash has a fixed set of
# counters and bounded IP/ASN/example fields, even when spam volume is high.
QUEUE_SCRIPT = """
local bucket = KEYS[1]
local slot = ARGV[1]
local ending = ARGV[2]
if redis.call('EXISTS', KEYS[2]) == 1 then
    bucket = KEYS[3]
    slot = ARGV[3]
    ending = ARGV[4]
end
redis.call('ZADD', KEYS[4], ending, slot)
redis.call('HINCRBY', bucket, 'count:' .. ARGV[5] .. ':' .. ARGV[6], 1)
redis.call('HINCRBY', bucket, 'total', 1)
local function bounded_count(prefix, value)
    if value == '' then return end
    local field = prefix .. ':' .. value
    if redis.call('HEXISTS', bucket, field) == 1 then
        redis.call('HINCRBY', bucket, field, 1)
    elseif tonumber(redis.call('HGET', bucket, prefix .. '_size') or '0') < 25 then
        redis.call('HINCRBY', bucket, prefix .. '_size', 1)
        redis.call('HSET', bucket, field, 1)
    end
end
bounded_count('ip', ARGV[7])
bounded_count('asn', ARGV[8])
return slot
"""

SEAL_SCRIPT = """
if redis.call('EXISTS', KEYS[2]) == 1 then
    return redis.call('HGETALL', KEYS[2])
end
if redis.call('EXISTS', KEYS[1]) == 0 then
    redis.call('ZREM', KEYS[4], ARGV[1])
    return {}
end
redis.call('RENAME', KEYS[1], KEYS[2])
redis.call('SET', KEYS[3], '1', 'EX', 604800)
return redis.call('HGETALL', KEYS[2])
"""

ACK_SCRIPT = """
redis.call('DEL', KEYS[1])
redis.call('ZREM', KEYS[2], ARGV[1])
return 1
"""


def _backend():
    """Use the same authenticated connection and namespace as lead protection."""
    backend = caches["lead_security"]
    return backend._cache.get_client(write=True), backend.make_key


def _slot_key(end: datetime) -> str:
    return end.astimezone(datetime_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _slot_end(now: datetime) -> datetime:
    now = timezone.localtime(now)
    for hour in HOURS_LOCAL:
        end = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if now < end:
            return end
    return (now + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)


def _previous_end(end: datetime) -> datetime:
    if end.hour == 21:
        return end.replace(hour=15)
    return (end - timedelta(days=1)).replace(hour=21)


def _keys(make_key, slot: str) -> tuple[str, str, str]:
    prefix = f"tg:lead-digest:v2:{slot}"
    return tuple(make_key(f"{prefix}:{part}") for part in ("live", "snapshot", "sealed"))


def queue_lead_digest(
    *,
    form_type: str,
    suspicious: bool,
    ip_address: str | None = None,
    asn: str | None = None,
    interval_seconds: int = 300,
    outcome: str = "blocked",
    entity_id=None,
) -> bool:
    """Count an attempt without sending or making customer submission depend on Redis.

    ``interval_seconds`` remains accepted for callers from older releases. It no
    longer changes the fixed reporting windows. Customer records and review
    notifications are persisted independently by the form handler.
    """
    del interval_seconds, entity_id
    form_type = form_type if form_type in FORM_LABELS else "lead"
    category = "review" if outcome in {"review", "suspected", "saved_for_review", "quarantined"} else "blocked"
    if not suspicious and outcome == "accepted":
        category = "accepted"
    try:
        client, make_key = _backend()
        end = _slot_end(timezone.now())
        next_end = _slot_end(end + timedelta(seconds=1))
        slot, next_slot = _slot_key(end), _slot_key(next_end)
        live, _, sealed = _keys(make_key, slot)
        next_live, _, _ = _keys(make_key, next_slot)
        client.eval(
            QUEUE_SCRIPT,
            4,
            live,
            sealed,
            next_live,
            make_key("tg:lead-digest:v2:windows"),
            slot,
            int(end.timestamp()),
            next_slot,
            int(next_end.timestamp()),
            form_type,
            category,
            str(ip_address or "")[:64],
            str(asn or "")[:64],
        )
        return True
    except Exception as exc:
        # The actual inquiry/review record is saved by the caller. Redis outages
        # must never turn a valid inquiry into a failed or discarded submission.
        _warn("Lead digest counter unavailable; customer handling continues", exc)
        return False


def _decode_hash(raw) -> dict[str, str]:
    def decode(value):
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    if isinstance(raw, dict):
        return {decode(k): decode(v) for k, v in raw.items()}
    return {decode(raw[i]): decode(raw[i + 1]) for i in range(0, len(raw), 2)}


def _count(state: dict[str, str], key: str) -> int:
    try:
        return int(state.get(key, 0))
    except (ValueError, TypeError):
        return 0


def _report(state: dict[str, str], end: datetime) -> str:
    end = timezone.localtime(end)
    start = _previous_end(end)
    review = sum(_count(state, f"count:{form}:review") for form in FORM_LABELS)
    blocked = sum(_count(state, f"count:{form}:blocked") for form in FORM_LABELS)
    accepted = sum(_count(state, f"count:{form}:accepted") for form in FORM_LABELS)
    lines = [
        "<b>Lead activity summary</b>",
        f"Period: {start:%b %d %H:%M} – {end:%b %d %H:%M} ({html.escape(str(end.tzinfo))})",
        f"Saved for review: {review}",
        f"Blocked attempts: {blocked}",
    ]
    if accepted:
        lines.append(f"Accepted inquiries: {accepted}")
    for form, label in FORM_LABELS.items():
        parts = []
        for category, suffix in (("review", "for review"), ("blocked", "blocked"), ("accepted", "accepted")):
            count = _count(state, f"count:{form}:{category}")
            if count:
                parts.append(f"{count} {suffix}")
        if parts:
            lines.append(f"{label}: {', '.join(parts)}")
    base_url = str(getattr(settings, "PUBLIC_BASE_URL", "") or getattr(settings, "SITE_URL", "") or "https://badguymotors.com").rstrip("/")
    review_path = str(getattr(settings, "LEAD_REVIEW_ADMIN_PATH", "/admin/core/leadsubmissionevent/?outcome__exact=suspected"))
    if review:
        lines.append(f'<a href="{html.escape(base_url + review_path, quote=True)}">Open saved requests for review</a>')
    lines.append(f'<a href="{html.escape(base_url + "/admin/core/leadsubmissionevent/", quote=True)}">Submission log</a>')
    return "\n".join(lines)


def send_due_lead_digest(now: datetime | None = None, *, force: bool = False) -> int:
    """Queue one combined report per closed window and recipient.

    Multiple schedulers are safe: Redis seals each snapshot atomically and the
    delivery table enforces a unique recipient/dedupe key. Work per tick is
    bounded so a long outage does not hold the bot loop indefinitely.

    ``force`` is accepted for command compatibility; a reporting window must
    still end before it can be sealed. Early sealing would mislabel later
    arrivals and undermine the guarantee of one complete report per window.
    """
    from .delivery import queued_message_count
    from .models import TelegramBotSettings, TelegramMessageLog
    from .services import send_telegram_message

    settings_obj = TelegramBotSettings.load_active()
    if not settings_obj:
        return 0
    recipients = list(dict.fromkeys(settings_obj.chat_id_list))
    if not recipients:
        return 0
    now = now or timezone.now()
    del force
    delivered = 0
    try:
        client, make_key = _backend()
        index = make_key("tg:lead-digest:v2:windows")
        due = client.zrangebyscore(index, "-inf", now.timestamp(), start=0, num=4)
        for raw_slot in due:
            slot = raw_slot.decode() if isinstance(raw_slot, bytes) else str(raw_slot)
            end = datetime.strptime(slot, "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime_timezone.utc)
            live, snapshot, sealed = _keys(make_key, slot)
            raw = client.eval(SEAL_SCRIPT, 4, live, snapshot, sealed, index, slot)
            state = _decode_hash(raw)
            if not state:
                continue
            dedupe_key = f"lead-digest:{slot}"
            delivered += send_telegram_message(
                _report(state, end),
                event_type=TelegramMessageLog.EVENT_DIGEST,
                chat_ids=recipients,
                dedupe_key=dedupe_key,
                entity_type="lead_digest",
                entity_id=slot,
                digest_slot=slot,
            )
            if queued_message_count(dedupe_key, recipients) == len(recipients):
                client.eval(ACK_SCRIPT, 2, snapshot, index, slot)
    except Exception as exc:
        _warn("Lead digest delivery deferred; snapshot retained for retry", exc)
    return delivered
