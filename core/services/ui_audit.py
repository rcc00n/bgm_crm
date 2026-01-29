from __future__ import annotations

import html
import logging
import re
import time
from datetime import timedelta
from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import Resolver404, get_resolver, resolve
from django.utils import timezone

from core.models import ClientUiCheckRun, UserRole
from notifications import services as telegram_services
from notifications.models import TelegramMessageLog

logger = logging.getLogger(__name__)

def _int_setting(name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


MAX_PAGES = _int_setting("CLIENT_UI_CHECK_MAX_PAGES", 120)
MAX_DEPTH = _int_setting("CLIENT_UI_CHECK_MAX_DEPTH", 3)
MAX_LINKS_PER_PAGE = _int_setting("CLIENT_UI_CHECK_MAX_LINKS_PER_PAGE", 250)
INTERVAL_DAYS = _int_setting("CLIENT_UI_CHECK_INTERVAL_DAYS", 3)

SAFE_PREFIXES = (
    "/accounts/",
    "/store/",
    "/dealer/",
    "/services/",
    "/legal/",
    "/project-journal/",
    "/our-story/",
    "/financing/",
    "/merch/",
)

SKIP_PREFIXES = (
    "/admin/",
    "/accounts/api/",
    "/analytics/",
    "/site-notice/",
    "/services/lead/",
    "/store/cart/add/",
    "/store/cart/remove/",
)

SKIP_PATHS = (
    "/accounts/logout/",
)

UNSAFE_TOKENS = (
    "/delete/",
    "/remove/",
    "/cancel/",
    "/reschedule/",
    "/export/",
    "/download/",
    "/logout/",
)

STATIC_EXTENSIONS = {
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".webp",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".pdf",
    ".zip",
    ".csv",
    ".xlsx",
}

IGNORED_WARNING_DETAILS = {
    "Button without action",
    "Anchor with empty href (#) and no handler",
}


@dataclass
class UrlCheckResult:
    url: str
    status_code: int | None
    context: str
    error: str | None
    content_type: str | None
    redirect_to: str | None


class HtmlAuditParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, Any]] = []
        self.forms: list[dict[str, Any]] = []
        self.buttons: list[dict[str, Any]] = []
        self._form_stack: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k: (v or "") for k, v in attrs}
        if tag == "a":
            self.links.append({
                "href": attr_map.get("href", ""),
                "role": attr_map.get("role", ""),
                "onclick": attr_map.get("onclick", ""),
                "data": {k: v for k, v in attr_map.items() if k.startswith("data-")},
            })
            return

        if tag == "form":
            form = {
                "action": attr_map.get("action", ""),
                "method": (attr_map.get("method", "") or "get").lower(),
                "id": attr_map.get("id", ""),
            }
            self.forms.append(form)
            self._form_stack.append(form)
            return

        if tag == "button" or (tag == "input" and attr_map.get("type") in {"submit", "button"}):
            self.buttons.append({
                "type": attr_map.get("type", ""),
                "onclick": attr_map.get("onclick", ""),
                "data": {k: v for k, v in attr_map.items() if k.startswith("data-")},
                "in_form": bool(self._form_stack),
            })
            return

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._form_stack:
            self._form_stack.pop()


def _sanitize_host(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    if not value or value == "*":
        return None
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        value = parsed.netloc or parsed.path
    value = value.lstrip(".")
    return value or None


def _preferred_host() -> str:
    allowed = getattr(settings, "ALLOWED_HOSTS", []) or []
    for host in allowed:
        cleaned = _sanitize_host(host)
        if cleaned:
            return cleaned
    return "localhost"


def _allowed_hosts() -> set[str]:
    allowed = {
        host for host in (_sanitize_host(h) for h in (getattr(settings, "ALLOWED_HOSTS", []) or []))
        if host
    }
    allowed.update({"testserver", "localhost", "127.0.0.1", _preferred_host()})
    return allowed


def _is_static_asset(path: str) -> bool:
    lowered = path.lower()
    return any(lowered.endswith(ext) for ext in STATIC_EXTENSIONS)


def _is_safe_prefix(path: str) -> bool:
    if path == "/":
        return True
    return any(path.startswith(prefix) for prefix in SAFE_PREFIXES)


def _is_skip_url(path: str) -> bool:
    if path in SKIP_PATHS:
        return True
    if any(path.startswith(prefix) for prefix in SKIP_PREFIXES):
        return True
    if any(token in path for token in UNSAFE_TOKENS):
        return True
    return False


def _normalize_url(raw: str, base_url: str) -> str | None:
    if not raw:
        return None
    trimmed = raw.strip()
    if not trimmed or trimmed.startswith("#"):
        return None
    lowered = trimmed.lower()
    if lowered.startswith("mailto:") or lowered.startswith("tel:") or lowered.startswith("javascript:"):
        return None

    absolute = urljoin(base_url, trimmed)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc and parsed.netloc not in _allowed_hosts():
        return None
    path = parsed.path or "/"
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


def _path_only(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path or "/"


def _check_resolve(path: str) -> bool:
    try:
        resolve(path)
        return True
    except Resolver404:
        if path != "/" and not path.endswith("/"):
            try:
                resolve(path + "/")
                return True
            except Resolver404:
                return False
        return False


def _extract_onclick_url(onclick: str) -> str | None:
    if not onclick:
        return None
    match = re.search(r"['\"](/[^'\"]+)['\"]", onclick)
    if match:
        return match.group(1)
    return None


def _seed_urls_from_patterns() -> set[str]:
    urls: set[str] = set()

    def walk(patterns: Iterable[Any], prefix: str = "") -> None:
        for entry in patterns:
            if hasattr(entry, "url_patterns"):
                walk(entry.url_patterns, prefix + str(entry.pattern))
            else:
                pattern_text = prefix + str(entry.pattern)
                if any(ch in pattern_text for ch in ("<", ">", "(", ")", "^", "$")):
                    continue
                if not pattern_text:
                    urls.add("/")
                    continue
                path = "/" + pattern_text.lstrip("/")
                urls.add(path)

    walk(get_resolver().url_patterns)
    return urls


def _seed_urls_from_data() -> set[str]:
    seeds: set[str] = set()
    try:
        from store.models import Category, Product
        from core.models import LegalPage

        categories = list(Category.objects.order_by("name")[:3])
        products = list(Product.objects.order_by("name")[:5])
        legal_pages = list(LegalPage.objects.order_by("slug")[:5])

        for cat in categories:
            if cat.slug:
                seeds.add(f"/store/category/{cat.slug}/")
        for product in products:
            if product.slug:
                seeds.add(f"/store/p/{product.slug}/")
        for page in legal_pages:
            if page.slug:
                seeds.add(f"/legal/{page.slug}/")
    except Exception:
        logger.exception("Failed to build dynamic UI check seeds")
    return seeds


def _pick_role_user(role_name: str):
    user_role = (
        UserRole.objects
        .select_related("user", "role")
        .filter(role__name=role_name, user__is_active=True)
        .first()
    )
    return user_role.user if user_role else None


def _build_clients() -> dict[str, Client]:
    host = _preferred_host()
    def make_client() -> Client:
        client = Client(HTTP_HOST=host)
        client.raise_request_exception = False
        return client

    clients = {"anon": make_client()}

    client_user = _pick_role_user("Client")
    if client_user:
        client = make_client()
        client.force_login(client_user)
        clients["client"] = client

    master_user = _pick_role_user("Master")
    if master_user:
        client = make_client()
        client.force_login(master_user)
        clients["master"] = client

    staff_user = get_user_model().objects.filter(is_staff=True, is_active=True).first()
    if staff_user:
        client = make_client()
        client.force_login(staff_user)
        clients["staff"] = client

    return clients


def _fetch_with_context(url: str, clients: dict[str, Client]) -> UrlCheckResult:
    def attempt(label: str) -> UrlCheckResult:
        client = clients[label]
        try:
            response = client.get(url, follow=False)
        except Exception as exc:
            return UrlCheckResult(url, None, label, f"{exc.__class__.__name__}: {exc}", None, None)

        redirect_to = None
        if response.status_code in {301, 302, 303, 307, 308}:
            redirect_to = response.headers.get("Location")
        content_type = response.headers.get("Content-Type")
        return UrlCheckResult(url, response.status_code, label, None, content_type, redirect_to)

    base_result = attempt("anon")
    if base_result.status_code in {301, 302} and base_result.redirect_to:
        location = base_result.redirect_to
        if "login" in location or "accounts/login" in location:
            for label in ("client", "master", "staff"):
                if label not in clients:
                    continue
                auth_result = attempt(label)
                if auth_result.status_code and auth_result.status_code < 400:
                    return auth_result
            return base_result
    if base_result.status_code == 403:
        for label in ("client", "master", "staff"):
            if label not in clients:
                continue
            auth_result = attempt(label)
            if auth_result.status_code and auth_result.status_code < 400:
                return auth_result
    return base_result


def _fetch_body(url: str, client: Client) -> tuple[str, str | None, int | None, str | None]:
    try:
        response = client.get(url, follow=True)
    except Exception as exc:
        return "", None, None, f"{exc.__class__.__name__}: {exc}"

    status_code = getattr(response, "status_code", None)
    content_type = response.headers.get("Content-Type")
    if content_type and "text/html" not in content_type:
        return "", content_type, status_code, None
    charset = response.charset or "utf-8"
    try:
        body = response.content.decode(charset, errors="replace")
    except Exception:
        body = response.content.decode("utf-8", errors="replace")
    return body, content_type, status_code, None


def _format_status(status: str) -> str:
    return {
        ClientUiCheckRun.Status.SUCCESS: "✅ Success",
        ClientUiCheckRun.Status.WARNING: "⚠️ Warning",
        ClientUiCheckRun.Status.FAILED: "❌ Failed",
        ClientUiCheckRun.Status.RUNNING: "⏳ Running",
        ClientUiCheckRun.Status.SKIPPED: "⏭ Skipped",
    }.get(status, status)


def _telegram_report(run: ClientUiCheckRun) -> str:
    stats = run.report.get("stats", {}) if run.report else {}
    issues = run.report.get("issues", []) if run.report else []
    error_message = run.report.get("error") if run.report else None

    header = f"<b>Client UI check — {timezone.localtime(run.started_at).strftime('%Y-%m-%d %H:%M')}</b>"
    status_line = f"Status: {_format_status(run.status)}"
    lines = [
        header,
        status_line,
        (
            f"Pages: {stats.get('pages', 0)} · "
            f"Links: {stats.get('links', 0)} · "
            f"Buttons: {stats.get('buttons', 0)} · "
            f"Forms: {stats.get('forms', 0)}"
        ),
        (
            f"Failures: {stats.get('failures', 0)} · "
            f"Warnings: {stats.get('warnings', 0)} · "
            f"Skipped: {stats.get('skipped', 0)}"
        ),
    ]

    duration_ms = run.duration_ms or 0
    if duration_ms:
        lines.append(f"Duration: {duration_ms / 1000:.1f}s")

    if error_message:
        lines.append(f"Error: {html.escape(str(error_message)[:400])}")

    if issues:
        def sort_key(item: dict[str, str]) -> int:
            level = (item.get("level") or "").upper()
            return 0 if level == "FAIL" else 1

        issues = sorted(issues, key=sort_key)
        lines.append("")
        lines.append("Top issues:")
        max_items = 10
        for idx, issue in enumerate(issues[:max_items], start=1):
            level = issue.get("level", "WARN").upper()
            target = issue.get("target", "")
            detail = issue.get("detail", "")
            lines.append(
                f"{idx}) {html.escape(level)} {html.escape(target)} — {html.escape(detail)}"
            )
        if len(issues) > max_items:
            lines.append(f"… and {len(issues) - max_items} more")

    return "\n".join(lines)


def _build_page_seed_list() -> list[str]:
    seeds = _seed_urls_from_patterns() | _seed_urls_from_data()
    safe = {
        url for url in seeds
        if _is_safe_prefix(url)
        and not _is_skip_url(url)
        and not _is_static_asset(url)
    }
    return sorted(safe)


def _is_due(last_run: ClientUiCheckRun | None) -> bool:
    if not last_run:
        return True
    return last_run.started_at <= timezone.now() - timedelta(days=INTERVAL_DAYS)


def run_client_ui_check(*, trigger: str, triggered_by=None, force: bool = False, send_telegram: bool = True) -> ClientUiCheckRun | None:
    last_run = ClientUiCheckRun.objects.exclude(status=ClientUiCheckRun.Status.RUNNING).first()
    if not force and not _is_due(last_run):
        return None

    stale_cutoff = timezone.now() - timedelta(hours=6)
    existing = ClientUiCheckRun.objects.filter(status=ClientUiCheckRun.Status.RUNNING, started_at__gte=stale_cutoff).first()
    if existing:
        return existing

    run = ClientUiCheckRun.objects.create(
        trigger=trigger,
        status=ClientUiCheckRun.Status.RUNNING,
        triggered_by=triggered_by,
    )

    started = time.monotonic()
    try:
        if MAX_PAGES <= 0:
            raise ValueError("CLIENT_UI_CHECK_MAX_PAGES must be > 0.")
        report = _perform_ui_audit()
        stats = report.get("stats", {})
        failures = stats.get("failures", 0)
        warnings = stats.get("warnings", 0)
        status = ClientUiCheckRun.Status.SUCCESS
        if failures:
            status = ClientUiCheckRun.Status.FAILED
        elif warnings:
            status = ClientUiCheckRun.Status.WARNING

        run.status = status
        run.total_pages = stats.get("pages", 0)
        run.total_links = stats.get("links", 0)
        run.total_forms = stats.get("forms", 0)
        run.total_buttons = stats.get("buttons", 0)
        run.failures_count = failures
        run.warnings_count = warnings
        run.skipped_count = stats.get("skipped", 0)
        run.report = report
        run.summary = report.get("summary", "")
    except Exception as exc:
        run.status = ClientUiCheckRun.Status.FAILED
        run.summary = f"{exc.__class__.__name__}: {exc}"
        run.failures_count = 1
        run.report = {
            "summary": run.summary,
            "error": run.summary,
            "stats": {
                "pages": 0,
                "links": 0,
                "buttons": 0,
                "forms": 0,
                "failures": 1,
                "warnings": 0,
                "skipped": 0,
            },
            "issues": [{"level": "FAIL", "target": "audit", "detail": run.summary}],
        }
        logger.exception("Client UI check failed")
    finally:
        run.finished_at = timezone.now()
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.save(
            update_fields=[
                "status",
                "finished_at",
                "duration_ms",
                "total_pages",
                "total_links",
                "total_forms",
                "total_buttons",
                "failures_count",
                "warnings_count",
                "skipped_count",
                "report",
                "summary",
            ]
        )

    if send_telegram:
        message = _telegram_report(run)
        telegram_services.send_telegram_message(
            message,
            event_type=TelegramMessageLog.EVENT_UI_CHECK,
        )

    return run


def _perform_ui_audit() -> dict[str, Any]:
    clients = _build_clients()
    seed_urls = _build_page_seed_list()
    queue: deque[tuple[str, int]] = deque((url, 0) for url in seed_urls)
    visited: set[str] = set()
    issues: list[dict[str, str]] = []

    stats = {
        "pages": 0,
        "links": 0,
        "forms": 0,
        "buttons": 0,
        "failures": 0,
        "warnings": 0,
        "skipped": 0,
    }

    def add_warning(target: str, detail: str) -> None:
        if detail in IGNORED_WARNING_DETAILS:
            return
        issues.append({
            "level": "WARN",
            "target": target,
            "detail": detail,
        })
        stats["warnings"] += 1

    def add_failure(target: str, detail: str) -> None:
        issues.append({
            "level": "FAIL",
            "target": target,
            "detail": detail,
        })
        stats["failures"] += 1

    while queue and len(visited) < MAX_PAGES:
        current_url, depth = queue.popleft()
        if current_url in visited:
            continue
        visited.add(current_url)

        if _is_skip_url(current_url) or _is_static_asset(current_url) or not _is_safe_prefix(current_url):
            stats["skipped"] += 1
            continue

        result = _fetch_with_context(current_url, clients)
        stats["pages"] += 1

        if result.error:
            add_failure(current_url, result.error)
            continue

        if result.status_code and result.status_code >= 400:
            add_failure(current_url, f"HTTP {result.status_code}")
            continue

        if not result.status_code:
            add_failure(current_url, "No response status")
            continue

        if result.redirect_to and depth < MAX_DEPTH:
            redirect_url = _normalize_url(
                result.redirect_to,
                f"http://{_preferred_host()}{current_url}",
            )
            if redirect_url and redirect_url not in visited:
                queue.append((redirect_url, depth + 1))

        context_client = clients.get(result.context, clients["anon"])
        body, content_type, body_status, body_error = _fetch_body(current_url, context_client)
        if body_error:
            add_failure(current_url, body_error)
            continue
        if body_status and body_status >= 400:
            add_failure(current_url, f"HTTP {body_status}")
            continue
        if content_type and "text/html" not in content_type:
            continue

        parser = HtmlAuditParser()
        try:
            parser.feed(body)
        except Exception as exc:
            add_failure(current_url, f"{exc.__class__.__name__}: {exc}")
            continue

        stats["links"] += len(parser.links)
        stats["forms"] += len(parser.forms)
        stats["buttons"] += len(parser.buttons)

        base_url = f"http://{_preferred_host()}{current_url}"

        for link in parser.links[:MAX_LINKS_PER_PAGE]:
            href = link.get("href", "")
            data_attrs = link.get("data", {})
            onclick = link.get("onclick", "")
            candidate = href or data_attrs.get("data-href") or data_attrs.get("data-url") or _extract_onclick_url(onclick)
            normalized = _normalize_url(candidate or "", base_url)
            if not normalized:
                if href and href.strip() == "#" and not onclick and not data_attrs:
                    add_warning(current_url, "Anchor with empty href (#) and no handler")
                continue

            path = _path_only(normalized)
            if _is_static_asset(path):
                continue

            if _is_skip_url(path):
                stats["skipped"] += 1
                continue

            if not _is_safe_prefix(path):
                continue

            if not _check_resolve(path):
                add_failure(path, "URL does not resolve")
                continue

            if depth < MAX_DEPTH and normalized not in visited:
                queue.append((normalized, depth + 1))

        for form in parser.forms:
            action = form.get("action", "")
            method = (form.get("method", "") or "get").lower()
            normalized = _normalize_url(action or current_url, base_url)
            if not normalized:
                add_warning(current_url, "Form without action")
                continue

            path = _path_only(normalized)
            if _is_skip_url(path):
                stats["skipped"] += 1
                continue

            if not _check_resolve(path):
                add_failure(path, f"Form action unresolved ({method.upper()})")
                continue

            if method == "get" and depth < MAX_DEPTH and normalized not in visited:
                queue.append((normalized, depth + 1))

        for button in parser.buttons:
            if button.get("in_form"):
                continue
            onclick = button.get("onclick", "")
            data_attrs = button.get("data", {})
            candidate = data_attrs.get("data-href") or data_attrs.get("data-url") or _extract_onclick_url(onclick)
            if candidate:
                normalized = _normalize_url(candidate, base_url)
                if normalized and not _is_skip_url(normalized):
                    path = _path_only(normalized)
                    if not _check_resolve(path):
                        add_failure(path, "Button target unresolved")
                    elif depth < MAX_DEPTH and normalized not in visited:
                        queue.append((normalized, depth + 1))
                continue

            if onclick or data_attrs:
                continue

            add_warning(current_url, "Button without action")

    summary = (
        f"Checked {stats['pages']} page(s), "
        f"{stats['links']} link(s), "
        f"{stats['buttons']} button(s)."
    )

    return {
        "summary": summary,
        "stats": stats,
        "issues": issues[:200],
        "seed_count": len(seed_urls),
    }
