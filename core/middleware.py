import logging

from django.conf import settings
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

from core.models import AdminSidebarSeen, VisitorSession

logger = logging.getLogger(__name__)


class VisitorAnalyticsMiddleware:
    """
    Ensures every trackable request is associated with a VisitorSession so that
    frontend engagement events can be reconciled with server-side context.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        default_exclusions = [
            getattr(settings, "STATIC_URL", ""),
            getattr(settings, "MEDIA_URL", ""),
            "/favicon.ico",
            "/admin/",
        ]
        configured = getattr(settings, "ANALYTICS_PATH_EXCLUSIONS", None)
        self.excluded_prefixes = tuple(
            prefix for prefix in (configured or default_exclusions) if prefix
        )

    def __call__(self, request):
        request.visitor_session = None
        if self._should_track(request):
            try:
                request.visitor_session = self._get_or_create_session(request)
            except Exception:
                # Analytics must never break the request cycle.
                logger.exception("Failed to initialize visitor analytics session")
        response = self.get_response(request)
        return response

    def _should_track(self, request) -> bool:
        path = getattr(request, "path", "") or ""
        if not hasattr(request, "session"):
            return False
        for prefix in self.excluded_prefixes:
            if prefix and path.startswith(prefix):
                return False
        return True

    def _get_or_create_session(self, request):
        session_key = self._ensure_session_key(request)
        if not session_key:
            return None

        defaults = {
            "ip_address": self._get_ip(request),
            "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:1024],
            "referrer": (request.META.get("HTTP_REFERER") or "")[:512],
            "landing_path": (request.path or "")[:512],
            "landing_query": (request.META.get("QUERY_STRING") or "")[:512],
        }
        if getattr(request, "user", None) and request.user.is_authenticated:
            defaults.update(self._snapshot_user(request.user))

        session, created = VisitorSession.objects.get_or_create(
            session_key=session_key,
            defaults=defaults,
        )

        dirty_fields = []
        if not created:
            ip = self._get_ip(request)
            user_agent = (request.META.get("HTTP_USER_AGENT") or "")[:1024]
            if ip and ip != session.ip_address:
                session.ip_address = ip
                dirty_fields.append("ip_address")
            if user_agent and user_agent != session.user_agent:
                session.user_agent = user_agent
                dirty_fields.append("user_agent")
            if not session.landing_path:
                session.landing_path = defaults["landing_path"]
                dirty_fields.append("landing_path")
            if not session.landing_query and defaults["landing_query"]:
                session.landing_query = defaults["landing_query"]
                dirty_fields.append("landing_query")

        if getattr(request, "user", None) and request.user.is_authenticated:
            snapshot = self._snapshot_user(request.user)
            if (
                session.user_id != request.user.id
                or session.user_email_snapshot != snapshot["user_email_snapshot"]
                or session.user_name_snapshot != snapshot["user_name_snapshot"]
            ):
                session.user = request.user
                session.user_email_snapshot = snapshot["user_email_snapshot"]
                session.user_name_snapshot = snapshot["user_name_snapshot"]
                dirty_fields.extend(["user", "user_email_snapshot", "user_name_snapshot"])

        if dirty_fields:
            session.save(update_fields=sorted(set(dirty_fields)))

        return session

    @staticmethod
    def _ensure_session_key(request):
        session_key = request.session.session_key
        if not session_key:
            request.session.save()
            session_key = request.session.session_key
        return session_key

    @staticmethod
    def _get_ip(request):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")

    @staticmethod
    def _snapshot_user(user):
        full_name = user.get_full_name() or ""
        fallback = user.username or ""
        return {
            "user": user,
            "user_email_snapshot": user.email or "",
            "user_name_snapshot": full_name or fallback,
        }


class AdminSidebarSeenMiddleware(MiddlewareMixin):
    """
    Marks admin sidebar items as seen once a staff user opens the model page.
    """

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method not in ("GET", "HEAD"):
            return None

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or not user.is_staff:
            return None

        path = getattr(request, "path", "") or ""
        if not path.startswith("/admin/"):
            return None

        app_label = view_kwargs.get("app_label")
        model_name = view_kwargs.get("model_name")
        if not app_label or not model_name:
            return None

        has_access = any(
            user.has_perm(f"{app_label}.{perm}_{model_name}")
            for perm in ("view", "change", "add", "delete")
        )
        if not has_access:
            return None

        AdminSidebarSeen.objects.update_or_create(
            user=user,
            app_label=app_label,
            model_name=model_name,
            defaults={"last_seen_at": timezone.now()},
        )
        return None
