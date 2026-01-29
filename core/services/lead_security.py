from __future__ import annotations

import hashlib
import ipaddress
import time
import uuid
from dataclasses import dataclass
from typing import Any

import logging
from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)
HONEYPOT_FIELD = getattr(settings, "LEAD_FORM_HONEYPOT_FIELD", "company")
TOKEN_SALT = "lead-form-token"

TOKEN_MAX_AGE_SECONDS = int(
    getattr(settings, "LEAD_FORM_TOKEN_MAX_AGE_SECONDS", 60 * 30)
)
MIN_AGE_SECONDS_BY_PURPOSE = {
    "site_notice": int(getattr(settings, "LEAD_FORM_MIN_AGE_SECONDS_SITE_NOTICE", 6)),
    "service_lead": int(getattr(settings, "LEAD_FORM_MIN_AGE_SECONDS_SERVICE_LEAD", 6)),
}

RATE_WINDOW_SECONDS = int(getattr(settings, "LEAD_RATE_LIMIT_WINDOW_SECONDS", 60 * 10))
RATE_LIMITS_BY_PURPOSE: dict[str, dict[str, int]] = {
    "site_notice": {
        "ip": int(getattr(settings, "LEAD_RATE_LIMIT_SITE_NOTICE_IP", 5)),
        "subnet": int(getattr(settings, "LEAD_RATE_LIMIT_SITE_NOTICE_SUBNET", 40)),
        "session": int(getattr(settings, "LEAD_RATE_LIMIT_SITE_NOTICE_SESSION", 2)),
        "asn": int(getattr(settings, "LEAD_RATE_LIMIT_SITE_NOTICE_ASN", 50)),
    },
    "service_lead": {
        "ip": int(getattr(settings, "LEAD_RATE_LIMIT_SERVICE_IP", 5)),
        "subnet": int(getattr(settings, "LEAD_RATE_LIMIT_SERVICE_SUBNET", 40)),
        "session": int(getattr(settings, "LEAD_RATE_LIMIT_SERVICE_SESSION", 2)),
        "asn": int(getattr(settings, "LEAD_RATE_LIMIT_SERVICE_ASN", 50)),
    },
}

SUSPECT_SCORE_THRESHOLD = int(getattr(settings, "LEAD_SUSPECT_SCORE_THRESHOLD", 3))
BLOCK_SCORE_THRESHOLD = int(getattr(settings, "LEAD_BLOCK_SCORE_THRESHOLD", 6))
FAST_SUBMIT_SECONDS = int(getattr(settings, "LEAD_FAST_SUBMIT_SECONDS", 5))
UA_BURST_LIMIT = int(getattr(settings, "LEAD_UA_BURST_LIMIT", 25))

DISPOSABLE_EMAIL_DOMAINS = {
    "10minutemail.com",
    "10minutemail.net",
    "10minutemail.org",
    "guerrillamail.com",
    "guerrillamail.net",
    "mailinator.com",
    "mailinator.net",
    "yopmail.com",
    "yopmail.net",
    "yopmail.fr",
    "yopmail.org",
    "temp-mail.org",
    "temp-mail.com",
    "tempail.com",
    "trashmail.com",
    "trashmail.net",
    "discard.email",
    "getnada.com",
    "getnada.org",
    "inboxbear.com",
    "maildrop.cc",
    "mintemail.com",
    "mohmal.com",
    "sharklasers.com",
    "fakeinbox.com",
    "throwawaymail.com",
    "dispostable.com",
    "tempmail.dev",
    "tempmailo.com",
}


@dataclass
class RateLimitResult:
    exceeded: bool
    reasons: list[str]
    counts: dict[str, int]


@dataclass
class LeadEvaluation:
    action: str
    score: int
    reasons: list[str]
    token_valid: bool
    token_error: str | None
    token_age_seconds: int | None
    time_on_page_ms: int | None
    session_first_seen_at: timezone.datetime | None
    ip_address: str | None
    subnet: str | None
    user_agent: str
    accept_language: str
    referer: str
    origin: str
    path: str
    cf_country: str
    cf_asn: str
    cf_asn_org: str
    session_key_hash: str
    ua_count: int
    rate_limit: RateLimitResult
    has_session_cookie: bool
    honeypot_hit: bool
    email_domain: str


@dataclass
class TokenValidation:
    valid: bool
    error: str | None
    age_seconds: int | None


def _now_ts() -> int:
    return int(time.time())


def _hash_session_key(session_key: str | None) -> str:
    if not session_key:
        return ""
    secret = getattr(settings, "SECRET_KEY", "")
    digest = hashlib.sha256(f"{secret}:{session_key}".encode("utf-8")).hexdigest()
    return digest


def _safe_str(value: str | None, limit: int = 512) -> str:
    if not value:
        return ""
    return value[:limit]


def get_client_ip(request) -> str | None:
    cf_ip = request.META.get("HTTP_CF_CONNECTING_IP")
    if cf_ip:
        return cf_ip
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def get_ip_subnet(ip: str | None) -> str | None:
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr.version == 4:
        network = ipaddress.ip_network(f"{ip}/24", strict=False)
    else:
        network = ipaddress.ip_network(f"{ip}/64", strict=False)
    return str(network)


def ensure_session_key(request) -> str | None:
    session_key = request.session.session_key
    if not session_key:
        request.session.save()
        session_key = request.session.session_key
    return session_key


def get_session_first_seen(request) -> timezone.datetime | None:
    raw = request.session.get("lead_first_seen_at")
    if raw:
        try:
            parsed = timezone.datetime.fromisoformat(raw)
        except Exception:
            parsed = None
        else:
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
        if parsed:
            return parsed
    visitor = getattr(request, "visitor_session", None)
    if visitor and getattr(visitor, "created_at", None):
        return visitor.created_at
    return None


def build_form_token(*, session_key: str, purpose: str, issued_at: timezone.datetime | None = None) -> str:
    issued_at = issued_at or timezone.now()
    nonce = uuid.uuid4().hex
    payload = {
        "sid": session_key,
        "purpose": purpose,
        "nonce": nonce,
        "iat": int(issued_at.timestamp()),
    }
    return signing.dumps(payload, salt=TOKEN_SALT)


def validate_form_token(
    token: str | None,
    *,
    session_key: str | None,
    purpose: str,
) -> TokenValidation:
    if not token:
        return TokenValidation(False, "missing", None)
    try:
        payload = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE_SECONDS)
    except signing.SignatureExpired:
        return TokenValidation(False, "expired", None)
    except signing.BadSignature:
        return TokenValidation(False, "invalid", None)

    if not isinstance(payload, dict):
        return TokenValidation(False, "invalid", None)

    if payload.get("purpose") != purpose:
        return TokenValidation(False, "purpose", None)

    sid = payload.get("sid")
    if not session_key or sid != session_key:
        return TokenValidation(False, "session_mismatch", None)

    nonce = payload.get("nonce")
    if not nonce:
        return TokenValidation(False, "nonce_missing", None)

    iat = payload.get("iat")
    try:
        iat_int = int(iat)
    except (TypeError, ValueError):
        return TokenValidation(False, "iat_missing", None)

    age = _now_ts() - iat_int
    if age < 0:
        age = 0

    min_age = MIN_AGE_SECONDS_BY_PURPOSE.get(purpose, 6)
    if age < min_age:
        return TokenValidation(False, "too_fast", age)

    nonce_key = f"lead:nonce:{purpose}:{nonce}"
    if not cache.add(nonce_key, 1, timeout=TOKEN_MAX_AGE_SECONDS):
        return TokenValidation(False, "replay", age)

    return TokenValidation(True, None, age)


def _increment_counter(key: str, window: int) -> int:
    try:
        if cache.add(key, 1, timeout=window):
            return 1
        return int(cache.incr(key))
    except Exception:
        # If cache backends don't support incr, fall back to set/add.
        try:
            current = cache.get(key)
        except Exception:
            current = None
        count = int(current or 0) + 1
        try:
            cache.set(key, count, timeout=window)
        except Exception:
            pass
        return count


def check_rate_limits(
    *,
    purpose: str,
    ip_address: str | None,
    subnet: str | None,
    session_key: str | None,
    asn: str | None,
) -> RateLimitResult:
    limits = RATE_LIMITS_BY_PURPOSE.get(purpose, RATE_LIMITS_BY_PURPOSE["service_lead"])
    counts: dict[str, int] = {}
    reasons: list[str] = []

    if ip_address:
        key = f"lead:rl:{purpose}:ip:{ip_address}"
        counts["ip"] = _increment_counter(key, RATE_WINDOW_SECONDS)
        if counts["ip"] > limits.get("ip", 0):
            reasons.append("ip")

    if subnet:
        key = f"lead:rl:{purpose}:subnet:{subnet}"
        counts["subnet"] = _increment_counter(key, RATE_WINDOW_SECONDS)
        if counts["subnet"] > limits.get("subnet", 0):
            reasons.append("subnet")

    if asn:
        key = f"lead:rl:{purpose}:asn:{asn}"
        counts["asn"] = _increment_counter(key, RATE_WINDOW_SECONDS)
        if counts["asn"] > limits.get("asn", 0):
            reasons.append("asn")

    if session_key:
        key = f"lead:rl:{purpose}:session:{session_key}"
        counts["session"] = _increment_counter(key, RATE_WINDOW_SECONDS)
        if counts["session"] > limits.get("session", 0):
            reasons.append("session")

    return RateLimitResult(bool(reasons), reasons, counts)


def increment_user_agent_count(user_agent: str) -> int:
    if not user_agent:
        return 0
    digest = hashlib.sha256(user_agent.encode("utf-8")).hexdigest()[:16]
    key = f"lead:ua:{digest}"
    return _increment_counter(key, RATE_WINDOW_SECONDS)


def parse_time_on_page_ms(request) -> int | None:
    raw = (request.POST.get("form_rendered_at") or "").strip()
    if not raw:
        return None
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    now_ms = int(time.time() * 1000)
    elapsed = now_ms - value
    if elapsed < 0:
        return None
    if elapsed > 1000 * 60 * 60 * 24:
        return None
    return elapsed


def is_disposable_email(email: str | None) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.split("@")[-1].lower().strip()
    return domain in DISPOSABLE_EMAIL_DOMAINS


def evaluate_lead_submission(request, *, purpose: str, email: str | None = None) -> LeadEvaluation:
    ip_address = get_client_ip(request)
    subnet = get_ip_subnet(ip_address)
    session_key = request.session.session_key
    has_session_cookie = settings.SESSION_COOKIE_NAME in request.COOKIES
    user_agent = _safe_str(request.META.get("HTTP_USER_AGENT"), 1024)
    accept_language = _safe_str(request.META.get("HTTP_ACCEPT_LANGUAGE"), 512)
    referer = _safe_str(request.META.get("HTTP_REFERER"), 600)
    origin = _safe_str(request.META.get("HTTP_ORIGIN"), 300)
    path = _safe_str(getattr(request, "path", ""), 300)
    cf_country = _safe_str(request.META.get("HTTP_CF_IPCOUNTRY"), 12)
    cf_asn = _safe_str(request.META.get("HTTP_CF_ASN"), 40)
    cf_asn_org = _safe_str(request.META.get("HTTP_CF_ASN_ORGANIZATION"), 200)

    honeypot_hit = bool((request.POST.get(HONEYPOT_FIELD) or "").strip())
    token_raw = (request.POST.get("form_token") or "").strip()
    token_status = validate_form_token(token_raw, session_key=session_key, purpose=purpose)

    time_on_page_ms = parse_time_on_page_ms(request)
    session_first_seen_at = get_session_first_seen(request)

    rate_limit = check_rate_limits(
        purpose=purpose,
        ip_address=ip_address,
        subnet=subnet,
        session_key=session_key,
        asn=cf_asn or None,
    )

    ua_count = increment_user_agent_count(user_agent)
    email_domain = ""
    if email and "@" in email:
        email_domain = email.split("@")[-1].lower().strip()

    score = 0
    reasons: list[str] = []

    if honeypot_hit:
        score += 999
        reasons.append("honeypot")

    if not token_status.valid:
        score += 999
        reasons.append(f"token:{token_status.error or 'invalid'}")

    if rate_limit.exceeded:
        score += 4
        reasons.append("rate_limit")

    if not referer and not origin:
        score += 2
        reasons.append("no_ref_or_origin")

    if time_on_page_ms is not None and time_on_page_ms < FAST_SUBMIT_SECONDS * 1000:
        score += 3
        reasons.append("fast_submit")

    if not has_session_cookie:
        score += 2
        reasons.append("no_session")

    if ua_count and ua_count >= UA_BURST_LIMIT:
        score += 2
        reasons.append("ua_burst")

    if is_disposable_email(email):
        score += 2
        reasons.append("disposable_email")

    action = "allow"
    if rate_limit.exceeded:
        action = "rate_limited"
    elif honeypot_hit or not token_status.valid:
        action = "blocked"
    elif score >= BLOCK_SCORE_THRESHOLD:
        action = "blocked"
    elif score >= SUSPECT_SCORE_THRESHOLD:
        action = "suspect"

    return LeadEvaluation(
        action=action,
        score=score,
        reasons=reasons,
        token_valid=token_status.valid,
        token_error=token_status.error,
        token_age_seconds=token_status.age_seconds,
        time_on_page_ms=time_on_page_ms,
        session_first_seen_at=session_first_seen_at,
        ip_address=ip_address,
        subnet=subnet,
        user_agent=user_agent,
        accept_language=accept_language,
        referer=referer,
        origin=origin,
        path=path,
        cf_country=cf_country,
        cf_asn=cf_asn,
        cf_asn_org=cf_asn_org,
        session_key_hash=_hash_session_key(session_key),
        ua_count=ua_count,
        rate_limit=rate_limit,
        has_session_cookie=has_session_cookie,
        honeypot_hit=honeypot_hit,
        email_domain=email_domain,
    )


def log_lead_submission(
    *,
    form_type: str,
    evaluation: LeadEvaluation,
    outcome: str,
    success: bool,
    validation_errors: str = "",
) -> None:
    from core.models import LeadSubmissionEvent

    flags: dict[str, Any] = {
        "reasons": evaluation.reasons,
        "token_error": evaluation.token_error,
        "token_age_seconds": evaluation.token_age_seconds,
        "rate_limit": evaluation.rate_limit.reasons,
        "rate_counts": evaluation.rate_limit.counts,
        "time_on_page_ms": evaluation.time_on_page_ms,
        "ua_count": evaluation.ua_count,
        "session_cookie": evaluation.has_session_cookie,
        "email_domain": evaluation.email_domain,
    }

    try:
        LeadSubmissionEvent.objects.create(
            form_type=form_type,
            outcome=outcome,
            success=success,
            suspicion_score=evaluation.score,
            validation_errors=_safe_str(validation_errors, 500),
            ip_address=evaluation.ip_address,
            user_agent=_safe_str(evaluation.user_agent, 1024),
            accept_language=_safe_str(evaluation.accept_language, 512),
            referer=_safe_str(evaluation.referer, 600),
            origin=_safe_str(evaluation.origin, 300),
            path=_safe_str(evaluation.path, 300),
            session_key_hash=evaluation.session_key_hash,
            session_first_seen_at=evaluation.session_first_seen_at,
            time_on_page_ms=evaluation.time_on_page_ms,
            cf_country=evaluation.cf_country,
            cf_asn=evaluation.cf_asn,
            cf_asn_org=evaluation.cf_asn_org,
            flags=flags,
        )
    except Exception:
        logger.exception("Failed to log lead submission event")
