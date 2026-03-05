# accounts/views.py
from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from datetime import timedelta
from collections import OrderedDict

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse, HttpResponse
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import TemplateView, ListView
from django.views.generic.edit import CreateView

from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.text import slugify
from django.db.models import OuterRef, Subquery, Count, Q
from django.db.models.functions import TruncMonth
from django.conf import settings
from django.template.defaultfilters import filesizeformat
import os

from core.models import (
    Service,
    Appointment,
    AppointmentStatusHistory,
    EmailSendLog,
    ClientReview,
    ClientFile,
    ClientPortalPageCopy,
    MerchPageCopy,
    LandingPageReview,
    PageFontSetting,
)
from core.services.fonts import build_page_font_context
from core.services.media import build_home_gallery_media
from core.services.page_sections import get_page_sections
from core.services.email_reporting import describe_email_types
from core.services.printful import get_printful_merch_feed
from core.utils import format_currency
from core.emails import build_email_html, send_html_email
from core.email_templates import email_brand_name, join_text_sections

from .forms import (
    ClientRegistrationForm,
    ClientProfileForm,
    VerifiedLoginForm,
)
from store.models import Category, MerchCategory, Order, Product, ProductOption
from store.utils_merch import normalize_merch_category

CLIENT_PORTAL_FILE_MAX_MB = getattr(settings, "CLIENT_PORTAL_FILE_MAX_MB", 10)
CLIENT_PORTAL_FILE_MAX_BYTES = CLIENT_PORTAL_FILE_MAX_MB * 1024 * 1024
CLIENT_PORTAL_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf"}
CLIENT_PORTAL_ALLOWED_MIME_TYPES = {"application/pdf"}

logger = logging.getLogger(__name__)
UserModel = get_user_model()
EMAIL_VERIFICATION_RESEND_MINUTES = int(getattr(settings, "EMAIL_VERIFICATION_RESEND_MINUTES", 10))


def _build_email_verification_url(request, user) -> str:
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return request.build_absolute_uri(
        reverse("verify-email", kwargs={"uidb64": uidb64, "token": token})
    )


def _send_email_verification(request, user, *, force: bool = False) -> bool:
    profile = getattr(user, "userprofile", None)
    if not profile:
        return False
    if not user.email:
        return False
    if profile.email_verified_at:
        return False

    now = timezone.now()
    if not force and profile.email_verification_sent_at:
        if now - profile.email_verification_sent_at < timedelta(minutes=EMAIL_VERIFICATION_RESEND_MINUTES):
            return False

    sender = (
        getattr(settings, "DEFAULT_FROM_EMAIL", None)
        or getattr(settings, "SUPPORT_EMAIL", None)
    )
    if not sender:
        logger.warning("Missing DEFAULT_FROM_EMAIL/SUPPORT_EMAIL for email verification.")
        raise ValueError("Email service is unavailable.")

    brand = email_brand_name()
    verify_url = _build_email_verification_url(request, user)
    expiry_seconds = int(getattr(settings, "PASSWORD_RESET_TIMEOUT", 60 * 60 * 72))
    expiry_hours = max(1, int(expiry_seconds / 3600))

    greeting_name = user.get_full_name() or user.username or "there"
    greeting = f"Hi {greeting_name},"
    intro_lines = [
        f"Thanks for creating your {brand} account.",
        "Please confirm your email address to finish setting up your account.",
    ]
    notice_lines = [f"This verification link expires in {expiry_hours} hours."]
    footer_lines = ["If you did not request this, you can ignore this email."]

    text_body = join_text_sections(
        [greeting],
        intro_lines,
        [f"Verify your email: {verify_url}"],
        notice_lines,
        footer_lines,
    )
    html_body = build_email_html(
        title="Verify your email",
        preheader="Confirm your email to activate your account.",
        greeting=greeting,
        intro_lines=intro_lines,
        notice_title="Security",
        notice_lines=notice_lines,
        footer_lines=footer_lines,
        cta_label="Verify email",
        cta_url=verify_url,
    )
    send_html_email(
        subject=f"{brand} - verify your email",
        text_body=text_body,
        html_body=html_body,
        from_email=sender,
        recipient_list=[user.email],
        email_type="email_verification",
    )

    profile.email_verification_sent_at = now
    profile.save(update_fields=["email_verification_sent_at"])
    return True

# =========================
# Аутентификация и доступ
# =========================
class RoleBasedLoginView(LoginView):
    """
    Логин с редиректами по ролям:
      • staff/superuser → /admin
      • Master → master_dashboard
      • Client → mainmenu
    """
    template_name = "registration/login.html"
    authentication_form = VerifiedLoginForm

    def get_success_url(self):
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return reverse("admin:index")

        role_names = set(
            user.userrole_set.select_related("role").values_list("role__name", flat=True)
        )
        if "Master" in role_names:
            return reverse("master_dashboard")
        if "Client" in role_names:
            return reverse("mainmenu")

        return super().get_success_url()

    def form_invalid(self, form):
        user = getattr(form, "unverified_user", None)
        if user:
            try:
                sent = _send_email_verification(self.request, user, force=False)
                if sent:
                    messages.info(
                        self.request,
                        "We sent you a new verification email. Please check your inbox.",
                    )
            except Exception:
                logger.exception("Failed to resend verification email to %s", user.email)
                messages.error(
                    self.request,
                    "We couldn't resend the verification email right now.",
                )
        return super().form_invalid(form)


class RoleRequiredMixin(LoginRequiredMixin):
    """
    Ограничение доступа по конкретной роли.
    """
    required_role: str | None = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if self.required_role and not request.user.userrole_set.filter(role__name=self.required_role).exists():
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class EmailVerificationView(View):
    def get(self, request, uidb64, token, *args, **kwargs):
        user = None
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = UserModel.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, UserModel.DoesNotExist):
            user = None

        if user and default_token_generator.check_token(user, token):
            profile = getattr(user, "userprofile", None)
            if profile and not profile.email_verified_at:
                profile.email_verified_at = timezone.now()
                profile.save(update_fields=["email_verified_at"])
            messages.success(request, "Email verified. You can sign in now.")
            return redirect("login")

        messages.error(request, "This verification link is invalid or expired.")
        return redirect("login")


# =========================
# Главная клиента (каталог)
# =========================
class MainMenuView(LoginRequiredMixin, TemplateView):
    template_name = "client/mainmenu.html"
    login_url = reverse_lazy("login")
    redirect_field_name = "next"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.userrole_set.filter(role__name="Client").exists():
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


# =========================
# Личный кабинет клиента
# =========================
class ClientDashboardView(LoginRequiredMixin, TemplateView):
    """
    GET  → страница и данные
    POST → сохранение профиля (User + UserProfile)
    """
    template_name = "client/dashboard.html"

    @staticmethod
    def _notification_tag(email_type: str) -> str:
        slug = (email_type or "").lower()
        if "appointment" in slug:
            return "Appointment"
        if slug.startswith("order_"):
            return "Order"
        if slug.startswith("email_verification"):
            return "Account"
        if slug.startswith("site_notice") or "cart" in slug:
            return "Offers"
        return "Update"

    @classmethod
    def _notification_summary(cls, email_type: str) -> str:
        tag = cls._notification_tag(email_type)
        if tag == "Appointment":
            return "Details about your booking were sent to your email."
        if tag == "Order":
            return "There is an update on your order."
        if tag == "Account":
            return "This message is about your account and sign-in."
        if tag == "Offers":
            return "A special offer or reminder was sent to you."
        return "A new message from Bad Guy Motors was sent to your email."

    @classmethod
    def _notification_title(cls, subject: str, email_type: str, meta_label: str) -> str:
        clean_subject = (subject or "").strip()
        if clean_subject:
            return clean_subject
        tag = cls._notification_tag(email_type)
        if tag == "Appointment":
            return "Appointment update"
        if tag == "Order":
            return "Order update"
        if tag == "Account":
            return "Account update"
        if tag == "Offers":
            return "Offer update"
        return (meta_label or "").strip() or "Update from Bad Guy Motors"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        now = timezone.now()

        ctx["portal_copy"] = ClientPortalPageCopy.get_solo()
        # профиль может отсутствовать → None
        ctx["profile"] = getattr(user, "userprofile", None)

        # быстрые действия — список услуг
        ctx["services"] = Service.objects.all().order_by("name")

        # подзапрос на последний статус записи
        latest_status = (
            AppointmentStatusHistory.objects.filter(appointment_id=OuterRef("pk"))
            .order_by("-set_at")
            .values("status__name")[:1]
        )

        # все записи клиента (для статистики/истории)
        qs = (
            Appointment.objects
            .filter(client=user)
            .select_related("service", "master")
            .annotate(current_status=Subquery(latest_status))
            .order_by("-start_time")
        )
        ctx["appointments"] = qs
        ctx["client_files"] = (
            ClientFile.objects
            .filter(user=user)
            .order_by("-uploaded_at")
        )
        ctx["client_file_max_mb"] = CLIENT_PORTAL_FILE_MAX_MB

        orders_qs = (
            Order.objects
            .select_related("user")
            .prefetch_related("items__product", "items__option")
            .filter(user=user)
            .order_by("-id")
        )
        orders = list(orders_qs)
        if not orders:
            email = (user.email or "").strip()
            if email:
                orders = list(
                    Order.objects
                    .select_related("user")
                    .prefetch_related("items__product", "items__option")
                    .filter(email__iexact=email)
                    .order_by("-id")
                )

        for order in orders:
            preview_image_url = ""
            for item in order.items.all():
                product = getattr(item, "product", None)
                if not product:
                    continue
                candidate = getattr(product, "main_image_url", "") or ""
                if candidate:
                    preview_image_url = candidate
                    break
            order.preview_image_url = preview_image_url
        ctx["orders"] = orders

        # прошлые и будущие
        ctx["recent_appointments"] = qs.filter(start_time__lt=now)[:5]

        # 🔹 все будущие (по возрастанию), исключая отменённые
        upcoming_qs = (
            qs.filter(start_time__gte=now)
              .exclude(current_status="Cancelled")
              .order_by("start_time")
        )
        ctx["upcoming_appointments"] = upcoming_qs
        ctx["next_appointment"] = upcoming_qs.first()  # для обратной совместимости

        # статистика по месяцам: всегда последние 6 месяцев (включая текущий)
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        def shift_month(dt, delta):
            month_index = (dt.month - 1) + delta
            year = dt.year + (month_index // 12)
            month = (month_index % 12) + 1
            return dt.replace(year=year, month=month, day=1)

        month_starts = [shift_month(current_month_start, delta) for delta in range(-5, 1)]
        window_start = month_starts[0]
        window_end = shift_month(current_month_start, 1)

        month_counts = (
            qs.filter(start_time__gte=window_start, start_time__lt=window_end)
            .annotate(month=TruncMonth("start_time"))
            .values("month")
            .annotate(cnt=Count("id"))
            .order_by("month")
        )
        month_count_map = {
            row["month"].strftime("%Y-%m"): row["cnt"]
            for row in month_counts
            if row.get("month")
        }
        chart_labels = [dt.strftime("%b") for dt in month_starts]
        chart_data = [month_count_map.get(dt.strftime("%Y-%m"), 0) for dt in month_starts]
        baseline = max(1, int(round(sum(chart_data) / len(chart_data)))) if chart_data else 1
        chart_potential = [baseline for _ in chart_data]

        ctx["chart_labels"] = chart_labels
        ctx["chart_data"] = chart_data
        ctx["chart_potential"] = chart_potential

        notification_emails: list[dict[str, object]] = []
        user_email = (user.email or "").strip().lower()
        if user_email:
            # Keep portal load fast and scan only the most recent send logs.
            recent_logs = EmailSendLog.objects.filter(success=True).only(
                "email_type",
                "subject",
                "recipients",
                "sent_at",
            ).order_by("-sent_at")[:500]
            matched_logs = []
            for log in recent_logs:
                recipients = log.recipients if isinstance(log.recipients, list) else []
                if any(
                    isinstance(recipient, str) and recipient.strip().lower() == user_email
                    for recipient in recipients
                ):
                    matched_logs.append(log)
                    if len(matched_logs) >= 20:
                        break

            type_meta = describe_email_types([log.email_type for log in matched_logs]) if matched_logs else {}
            for log in matched_logs:
                meta = type_meta.get(log.email_type, {})
                title = self._notification_title(log.subject, log.email_type, str(meta.get("label") or ""))
                summary = self._notification_summary(log.email_type)
                notification_emails.append(
                    {
                        "title": title,
                        "summary": summary,
                        "sent_at": log.sent_at,
                        "tag": self._notification_tag(log.email_type),
                    }
                )
        ctx["notification_emails"] = notification_emails

        return ctx

    def post(self, request, *args, **kwargs):
        """
        Форма профиля (вкладка Profile).
        Поля: first_name, last_name, email, phone, birth_date (YYYY-MM-DD).
        """
        form = ClientProfileForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect(reverse("dashboard") + "#profile")

        ctx = self.get_context_data()
        ctx["profile_form_errors"] = form.errors
        return self.render_to_response(ctx, status=400)


def serialize_client_file(file_obj: ClientFile) -> dict[str, str]:
    uploaded_at = file_obj.uploaded_at
    uploaded_at_iso = timezone.localtime(uploaded_at).isoformat() if uploaded_at else ""
    uploaded_at_display = (
        timezone.localtime(uploaded_at).strftime("%b %d, %Y %H:%M") if uploaded_at else ""
    )
    is_image = file_obj.is_image
    return {
        "id": str(file_obj.id),
        "name": file_obj.filename or os.path.basename(file_obj.file.name),
        "url": file_obj.file.url,
        "size": filesizeformat(file_obj.file_size) if file_obj.file_size else "—",
        "uploaded_at": uploaded_at_iso,
        "uploaded_at_display": uploaded_at_display,
        "uploaded_by": file_obj.get_uploaded_by_display(),
        "description": file_obj.description or "",
        "can_delete": file_obj.uploaded_by == ClientFile.USER,
        "delete_url": reverse("dashboard-file-delete", args=[file_obj.id]) if file_obj.uploaded_by == ClientFile.USER else "",
        "is_image": is_image,
    }


class ClientFileUploadView(LoginRequiredMixin, View):
    """
    Handles uploads from the Files tab inside the client dashboard.
    """

    def post(self, request, *args, **kwargs):
        uploaded = request.FILES.get("file")
        if not uploaded:
            return JsonResponse({"error": "Please choose a file."}, status=400)

        if uploaded.size > CLIENT_PORTAL_FILE_MAX_BYTES:
            return JsonResponse(
                {"error": f"File is too large. Limit: {CLIENT_PORTAL_FILE_MAX_MB} MB."},
                status=400,
            )

        if not self._is_allowed(uploaded):
            return JsonResponse(
                {"error": "Unsupported format. Only images or PDF files are allowed."},
                status=400,
            )

        description = (request.POST.get("description") or "").strip()[:255]
        client_file = ClientFile.objects.create(
            user=request.user,
            file=uploaded,
            description=description,
            uploaded_by=ClientFile.USER,
        )
        return JsonResponse({"file": serialize_client_file(client_file)}, status=201)

    def _is_allowed(self, uploaded_file) -> bool:
        content_type = (uploaded_file.content_type or "").lower()
        extension = os.path.splitext(uploaded_file.name)[1].lower()
        return (
            content_type.startswith("image/")
            or content_type in CLIENT_PORTAL_ALLOWED_MIME_TYPES
            or extension in CLIENT_PORTAL_ALLOWED_EXTENSIONS
        )


class ClientFileDeleteView(LoginRequiredMixin, View):
    """
    Allows a user to delete only the files they personally uploaded.
    """

    def post(self, request, file_id, *args, **kwargs):
        client_file = get_object_or_404(ClientFile, pk=file_id, user=request.user)
        if client_file.uploaded_by != ClientFile.USER:
            return JsonResponse(
                {"error": "Files uploaded by the team cannot be deleted here."},
                status=403,
            )
        client_file.delete()
        return JsonResponse({"ok": True})


# =========================
# Кабинет мастера
# =========================
class MasterDashboardView(RoleRequiredMixin, TemplateView):
    required_role = "Master"
    template_name = "master/dashboard.html"


# =========================
# Список записей клиента
# =========================
class ClientAppointmentsListView(RoleRequiredMixin, ListView):
    required_role = "Client"
    model = Appointment
    template_name = "client/appointments_list.html"
    paginate_by = 10

    def get_queryset(self):
        return (
            Appointment.objects
            .filter(client=self.request.user)
            .select_related("service", "master")
            .order_by("-start_time")
        )


# =========================
# Регистрация клиента (AJAX-friendly)
# =========================
class ClientRegisterView(CreateView):
    form_class = ClientRegistrationForm
    template_name = "registration/register_popup.html"
    success_url = None  # вычисляем в get_success_url()

    def form_valid(self, form):
        user = form.save()
        try:
            sent = _send_email_verification(self.request, user, force=True)
            if not sent:
                raise ValueError("Email verification was not sent.")
        except Exception:
            logger.exception("Failed to send verification email to %s", user.email)
            user.delete()
            if self.request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse(
                    {"__all__": ["Unable to send verification email right now."]},
                    status=500,
                )
            form.add_error(None, "Unable to send verification email right now.")
            return self.form_invalid(form)

        if self.request.headers.get("x-requested-with") == "XMLHttpRequest":
            return HttpResponse("OK")
        messages.success(self.request, "Check your email to verify your account.")
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        if self.request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(form.errors, status=400)
        return super().form_invalid(form)

    def get_success_url(self):
        return f"{reverse('login')}?registered=1"

# accounts/views.py
from django.views.generic import TemplateView
from core.models import ServiceCategory, Service

# accounts/views.py (или где у вас HomeView)
from django.views.generic import TemplateView
from core.models import Service, ServiceCategory, HomePageCopy, HomePageFAQItem, ProjectJournalEntry   # ваши модели услуг
from core.services.page_layout import build_layout_styles
from store.models import Product, Category as StoreCategory  # товары


def _select_home_products(
    products_qs,
    *,
    limit: int = 8,
    in_house_target: int = 4,
    candidate_limit: int = 200,
):
    # Pick newer items across distinct categories and prefer some in-house if available.
    candidates = list(products_qs[:candidate_limit])
    selected = []
    selected_ids = set()
    selected_categories = set()
    in_house_target = max(0, min(in_house_target, limit))

    def add_product(product):
        selected.append(product)
        selected_ids.add(product.id)
        if product.category_id:
            selected_categories.add(product.category_id)

    # Prefer a couple of in-house items from different categories.
    for product in candidates:
        if len(selected) >= in_house_target:
            break
        if not getattr(product, "is_in_house", False):
            continue
        if product.category_id in selected_categories:
            continue
        add_product(product)

    # Fill with distinct categories first.
    for product in candidates:
        if len(selected) >= limit:
            break
        if product.id in selected_ids:
            continue
        if product.category_id in selected_categories:
            continue
        add_product(product)

    # Fill remaining slots if there are not enough categories.
    for product in candidates:
        if len(selected) >= limit:
            break
        if product.id in selected_ids:
            continue
        add_product(product)

    # Ensure at least one in-house item is visible when available.
    if selected and not any(getattr(p, "is_in_house", False) for p in selected):
        fallback = products_qs.filter(is_in_house=True).first()
        if fallback and fallback.id not in selected_ids:
            replace_index = next(
                (idx for idx, item in enumerate(selected) if item.category_id == fallback.category_id),
                len(selected) - 1,
            )
            selected[replace_index] = fallback

    return selected


def _build_home_reviews(*, limit: int | None = None):
    # Home carousel should be bounded even when called without an explicit limit.
    limit = 12 if limit is None else max(1, int(limit))

    landing_qs = LandingPageReview.objects.filter(
        is_published=True,
    ).order_by("page", "display_order", "-created_at")[:limit]
    landing_reviews = list(landing_qs)
    if landing_reviews:
        return landing_reviews

    # Fallback to approved public reviews (store.StoreReview via core.ClientReview proxy).
    reviews = []
    approved_reviews = (
        ClientReview.objects.filter(
            product__isnull=True,
            status=ClientReview.Status.APPROVED,
        )
        .order_by("-approved_at", "-created_at")[:limit]
    )
    for review in approved_reviews:
        quote = (review.body or "").strip()
        if not quote:
            continue
        reviews.append(
            {
                "rating": review.rating,
                "quote": quote,
                "reviewer_name": (review.reviewer_name or "").strip() or "BGM Client",
                "reviewer_title": (review.reviewer_title or "").strip(),
                "star_range": range(review.rating or 0),
            }
        )
    return reviews


_HOME_QUICK_PICK_SPLIT_RE = re.compile(r"(?:\\s*(?:,|&|\\+|/|\\||•)\\s*|\\s+and\\s+)", re.IGNORECASE)


def _home_quick_pick_candidates(title: str, subtitle: str, *, hint: str = "") -> list[str]:
    # Build a small ordered list of phrases we can use to locate an existing Service.
    raw = " ".join([str(subtitle or "").strip(), str(title or "").strip(), str(hint or "").strip()]).strip()
    if not raw:
        return []

    parts: list[str] = []
    if subtitle:
        parts.extend([p.strip() for p in _HOME_QUICK_PICK_SPLIT_RE.split(str(subtitle)) if str(p or "").strip()])

    # Include title/hint as fallbacks when subtitle is generic (e.g. "Lift kits & 4-links").
    if title:
        parts.append(str(title).strip())
    if hint and hint.lower() not in str(title or "").lower():
        parts.append(str(hint).strip())

    expanded: list[str] = []
    for part in parts:
        cleaned = str(part or "").strip()
        if not cleaned:
            continue

        expanded.append(cleaned)

        normalized = re.sub(r"[^a-z0-9]+", " ", cleaned.lower()).strip()
        if not normalized:
            continue

        # Known abbreviations / common short-hands used in marketing copy.
        if normalized in {"scl"} or " scl " in f" {normalized} ":
            expanded.extend(["Smooth Criminal", "Smooth Criminal Liner"])
        if "armadillo" in normalized:
            expanded.extend(["Armadillo", "Armadillo Liner"])
        if normalized in {"ecu", "ecm"} or "ecu" in normalized or "ecm" in normalized:
            expanded.extend(["tuning", "ECU", "ECM"])
        if "4" in normalized and "link" in normalized:
            expanded.extend(["4 link", "4-link", "four link", "four-link"])

    # De-dupe while preserving order and ignore very short tokens.
    out: list[str] = []
    seen = set()
    for item in expanded:
        token = str(item or "").strip()
        if len(token) < 3:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _home_quick_pick_service_id(*, title: str, subtitle: str, hint: str = "") -> str:
    """
    Attempts to pick a Service UUID (as string) that matches the mobile "Quick picks" copy.
    Returns "" when no match can be found.
    """
    candidates = _home_quick_pick_candidates(title, subtitle, hint=hint)
    if not candidates:
        return ""

    category = None
    for needle in [title, hint]:
        needle = (needle or "").strip()
        if not needle:
            continue
        category = ServiceCategory.objects.filter(name__icontains=needle).order_by("id").first()
        if category:
            break

    scoped_qs = Service.objects.all()
    if category:
        scoped_qs = scoped_qs.filter(category=category)

    for phrase in candidates:
        match = scoped_qs.filter(name__icontains=phrase).order_by("name", "id").first()
        if match:
            return str(match.id)

    # If we found a category but none of the phrases match, still deep-link to a stable service inside it.
    if category:
        match = scoped_qs.order_by("name", "id").first()
        if match:
            return str(match.id)

    # Last resort: global phrase match.
    for phrase in candidates:
        match = Service.objects.filter(name__icontains=phrase).order_by("name", "id").first()
        if match:
            return str(match.id)

    return ""

class HomeView(TemplateView):
    template_name = "client/bgm_home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["font_settings"] = build_page_font_context(PageFontSetting.Page.HOME)
        home_copy = HomePageCopy.get_solo()
        ctx["home_copy"] = home_copy
        # Mobile "Quick picks": deep-link each tile to a real Service (opens booking modal) when possible.
        base_services_url = reverse("client-dashboard")
        ctx["services_mobile_action_1_url"] = f"{base_services_url}?q=fabrication#services"
        ctx["services_mobile_action_2_url"] = f"{base_services_url}?q=suspension#services"
        ctx["services_mobile_action_3_url"] = f"{base_services_url}?q=tuning#services"
        ctx["services_mobile_action_4_url"] = f"{base_services_url}?q=coating#services"
        try:
            s1 = _home_quick_pick_service_id(
                title=home_copy.services_mobile_action_1_title,
                subtitle=home_copy.services_mobile_action_1_subtitle,
                hint="fabrication",
            )
            s2 = _home_quick_pick_service_id(
                title=home_copy.services_mobile_action_2_title,
                subtitle=home_copy.services_mobile_action_2_subtitle,
                hint="suspension",
            )
            s3 = _home_quick_pick_service_id(
                title=home_copy.services_mobile_action_3_title,
                subtitle=home_copy.services_mobile_action_3_subtitle,
                hint="tuning",
            )
            s4 = _home_quick_pick_service_id(
                title=home_copy.services_mobile_action_4_title,
                subtitle=home_copy.services_mobile_action_4_subtitle,
                hint="coating",
            )
        except Exception:
            logger.exception("Failed to resolve home quick picks to service deep links.")
        else:
            if s1:
                ctx["services_mobile_action_1_url"] = f"{base_services_url}?q=fabrication&book={s1}#services"
            if s2:
                ctx["services_mobile_action_2_url"] = f"{base_services_url}?q=suspension&book={s2}#services"
            if s3:
                ctx["services_mobile_action_3_url"] = f"{base_services_url}?q=tuning&book={s3}#services"
            if s4:
                ctx["services_mobile_action_4_url"] = f"{base_services_url}?q=coating&book={s4}#services"
        from django.db.utils import OperationalError, ProgrammingError
        try:
            all_faq_items = list(
                HomePageFAQItem.objects.filter(home_page_copy=home_copy).order_by("order", "id")
            )
        except (OperationalError, ProgrammingError):
            # Backwards compatible: if the FAQ table isn't migrated yet, fall back to legacy fields.
            ctx["home_faq_legacy"] = True
            ctx["home_faq_items"] = []
        else:
            ctx["home_faq_legacy"] = False
            ctx["home_faq_items"] = [item for item in all_faq_items if item.is_published]
        ctx["page_sections"] = get_page_sections(home_copy)
        ctx["layout_styles"] = build_layout_styles(HomePageCopy, home_copy.layout_overrides)
        ctx["home_reviews"] = _build_home_reviews()
        # это у вас уже есть:
        ctx["categories"] = ServiceCategory.objects.all()
        ctx["filter_categories"] = ctx["categories"]
        ctx["product_filter_categories"] = (
            StoreCategory.objects.filter(products__is_active=True).distinct().order_by("name")
        )
        ctx["uncategorized"] = Service.objects.filter(category__isnull=True)
        ctx["has_any_services"] = Service.objects.exists()

        # НОВОЕ: 8 услуг для главной (витрина)
        ctx["home_services"] = (
            Service.objects.select_related("category")
            .order_by("-id")[:8]
        )

        # НОВОЕ: 8 товаров для главной (витрина)
        products_qs = (
            Product.objects.filter(is_active=True, is_in_house=True)
            .exclude(
                Q(merch_category__isnull=False)
                | Q(category__slug="merch")
                | Q(sku__startswith="PF-")
                | Q(slug__startswith="merch-")
            )
            .select_related("category")
            .prefetch_related("options", "discounts")
            .order_by("-created_at")
        )
        ctx["home_products"] = _select_home_products(products_qs, limit=8, in_house_target=4)
        gallery_url = (home_copy.gallery_cta_url or "").strip() or reverse("project-journal")
        gallery_posts = list(
            ProjectJournalEntry.objects.published()
            .filter(cover_image__isnull=False)
            .exclude(cover_image="")
            .order_by("-featured", "-published_at")[:4]
        )
        gallery_posts_iter = iter(gallery_posts)
        gallery_items = []
        for asset in build_home_gallery_media():
            if asset.get("is_custom"):
                gallery_items.append(
                    {
                        "image": asset.get("image"),
                        "src": asset["src"],
                        "alt": asset.get("alt") or "",
                        "title": asset.get("title") or "",
                        "caption": asset.get("caption") or "",
                        "url": gallery_url,
                    }
                )
                continue

            post = next(gallery_posts_iter, None)
            if post:
                gallery_items.append(
                    {
                        "image": post.cover_image,
                        "src": post.cover_image.url,
                        "alt": post.hero_title or post.title,
                        "title": post.hero_title or post.title,
                        "caption": post.result_highlight or post.excerpt,
                        "url": gallery_url,
                    }
                )
                continue

            gallery_items.append(
                {
                    "image": None,
                    "src": asset["src"],
                    "alt": asset.get("alt") or "",
                    "title": asset.get("title") or "",
                    "caption": asset.get("caption") or "",
                    "fallback_srcset_avif": asset.get("fallback_srcset_avif") or "",
                    "fallback_srcset_webp": asset.get("fallback_srcset_webp") or "",
                    "fallback_srcset_jpg": asset.get("fallback_srcset_jpg") or "",
                    "fallback_width": asset.get("fallback_width"),
                    "fallback_height": asset.get("fallback_height"),
                    "url": gallery_url,
                }
            )
        ctx["home_gallery_items"] = gallery_items
        ctx["home_gallery_url"] = gallery_url
        return ctx

    
# accounts/views.py
from django.views.generic import TemplateView

from django.views.generic import TemplateView
from core.models import ServiceCategory  # или ProductCategory если уже создал

class StoreView(TemplateView):
    template_name = "client/store.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = ServiceCategory.objects.prefetch_related("service_set")
        return ctx


PRINTFUL_MERCH_SYNC_KEY_PREFIX = "printful_merch_store_sync_v2"


def _printful_merch_limit_setting(default: int = 8) -> int:
    raw = getattr(settings, "PRINTFUL_MERCH_LIMIT", default)
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = default
    return max(0, parsed)


def _parse_merch_decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _build_printful_product_sku(product_id: int) -> str:
    return f"PF-{product_id}"


def _parse_printful_product_id_from_sku(value: str) -> int:
    raw = (value or "").strip().upper()
    if not raw.startswith("PF-"):
        return 0
    try:
        return int(raw[3:])
    except (TypeError, ValueError):
        return 0


def _build_printful_product_slug(product_id: int, name: str) -> str:
    base = slugify(name or "")[:140] or "item"
    return f"merch-{product_id}-{base}"[:200]


def _get_or_create_merch_category() -> Category:
    existing = Category.objects.filter(name__iexact="Merch").first() or Category.objects.filter(slug="merch").first()
    if existing:
        return existing
    return Category.objects.create(
        name="Merch",
        slug="merch",
        description="Printful merchandise catalog.",
    )


def _dedupe_option_name(name: str, *, index: int, used: set[str]) -> str:
    clean = (name or "").strip()[:120] or f"Option {index}"
    if clean not in used:
        used.add(clean)
        return clean

    attempt = 2
    while True:
        suffix = f" ({attempt})"
        candidate = f"{clean[: max(1, 120 - len(suffix))]}{suffix}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        attempt += 1


def _sync_printful_options_for_product(product: Product, variants: list[dict]) -> int | None:
    if not variants:
        ProductOption.objects.filter(product=product).update(is_active=False)
        return None

    seen_skus: list[str] = []
    used_names: set[str] = set()
    default_option_id = None

    for index, variant in enumerate(variants, start=1):
        raw_sku = str(variant.get("sku") or "").strip()[:64]
        variant_id = 0
        try:
            variant_id = int(variant.get("id") or 0)
        except (TypeError, ValueError):
            variant_id = 0

        option_sku = raw_sku or f"{product.sku}-VAR-{variant_id or index}"
        if option_sku in seen_skus:
            option_sku = f"{option_sku[:56]}-{index}"[:64]
        seen_skus.append(option_sku)

        option_name = _dedupe_option_name(str(variant.get("name") or ""), index=index, used=used_names)
        option_price = _parse_merch_decimal(variant.get("price"))

        option, _ = ProductOption.objects.update_or_create(
            sku=option_sku,
            defaults={
                "product": product,
                "name": option_name,
                "description": "",
                "is_separator": False,
                "option_column": 1,
                "price": option_price,
                "is_active": True,
                "sort_order": index,
            },
        )
        if default_option_id is None:
            default_option_id = option.id

    ProductOption.objects.filter(product=product).exclude(sku__in=seen_skus).update(is_active=False)
    return default_option_id


def _sync_printful_merch_products(products: list[dict]) -> None:
    if not products:
        return

    category = _get_or_create_merch_category()
    sync_full_catalog = _printful_merch_limit_setting() == 0
    default_currency = (getattr(settings, "DEFAULT_CURRENCY_CODE", "CAD") or "CAD").upper()
    merch_categories = list(MerchCategory.objects.all())
    merch_by_slug = {(cat.slug or "").strip().lower(): cat for cat in merch_categories if cat.slug}
    merch_by_name = {(cat.name or "").strip().lower(): cat for cat in merch_categories if cat.name}
    synced_skus: set[str] = set()

    def _resolve_merch_category(label_source: str) -> MerchCategory | None:
        source = (label_source or "").strip()
        if not source:
            return None
        category_key, category_label = normalize_merch_category(source)
        if not category_label:
            return None
        key = (category_key or "").strip().lower()
        name_key = category_label.strip().lower()
        existing = merch_by_slug.get(key) or merch_by_name.get(name_key)
        if existing:
            return existing
        created = MerchCategory.objects.create(
            name=category_label,
            slug=category_key or slugify(category_label)[:140],
            is_active=True,
        )
        merch_by_slug[(created.slug or "").strip().lower()] = created
        merch_by_name[(created.name or "").strip().lower()] = created
        return created

    for item in products:
        try:
            product_id = int(item.get("id") or 0)
        except (TypeError, ValueError):
            product_id = 0
        if product_id <= 0:
            continue

        name = (str(item.get("name") or "") or f"Merch item {product_id}").strip()[:180]
        sku = _build_printful_product_sku(product_id)
        synced_skus.add(sku)
        slug = _build_printful_product_slug(product_id, name)
        variants = [row for row in item.get("variants", []) if isinstance(row, dict)]

        variant_prices = []
        for variant in variants:
            price = _parse_merch_decimal(variant.get("price"))
            if price is not None:
                variant_prices.append(price)

        base_price = _parse_merch_decimal(item.get("base_price"))
        if base_price is None and variant_prices:
            base_price = min(variant_prices)
        if base_price is None:
            base_price = Decimal("0.00")

        currency = (str(item.get("currency") or "") or default_currency).strip().upper() or default_currency
        image_url = (str(item.get("image_url") or "") or "").strip()
        existing = Product.objects.filter(sku=sku).only("id", "is_active", "merch_category_id").first()
        merch_category = None
        if existing is None or not existing.merch_category_id:
            label_source = (item.get("category_label") or item.get("name") or "").strip()
            merch_category = _resolve_merch_category(label_source)
        defaults = {
            "slug": slug,
            "name": name,
            "category": category,
            "price": base_price,
            "is_in_house": True,
            "currency": currency,
            "inventory": 9999,
            # Preserve manual visibility toggles from admin.
            "is_active": existing.is_active if existing is not None else True,
            "short_description": "Fulfilled by Printful.",
            "description": f"Printful product #{product_id}",
            "contact_for_estimate": False,
            "estimate_from_price": None,
            "main_image": image_url,
        }
        if merch_category:
            defaults["merch_category"] = merch_category
        product, _ = Product.objects.update_or_create(sku=sku, defaults=defaults)
        _sync_printful_options_for_product(product, variants)

    if sync_full_catalog and synced_skus:
        Product.objects.filter(sku__startswith="PF-", is_active=True).exclude(sku__in=synced_skus).update(is_active=False)


def _build_synced_printful_merch_map(products: list[dict]) -> tuple[dict[int, dict], set[int]]:
    ids: list[int] = []
    for item in products:
        try:
            product_id = int(item.get("id") or 0)
        except (TypeError, ValueError):
            product_id = 0
        if product_id > 0:
            ids.append(product_id)
    if not ids:
        return {}, set()

    ids = sorted(set(ids))
    sync_key = f"{PRINTFUL_MERCH_SYNC_KEY_PREFIX}:{','.join(str(pid) for pid in ids)}"
    if not cache.get(sync_key):
        sync_ttl = 900
        try:
            _sync_printful_merch_products(products)
        except Exception:
            logger.exception("Failed to sync Printful merch catalog to store products.")
            sync_ttl = 60
        cache.set(sync_key, True, sync_ttl)

    resolved: dict[int, dict] = {}
    hidden_ids: set[int] = set()

    skus = [_build_printful_product_sku(product_id) for product_id in ids]
    store_products = (
        Product.objects.filter(sku__in=skus)
        .select_related("merch_category")
        .prefetch_related("options")
    )
    for product in store_products:
        product_id = _parse_printful_product_id_from_sku(product.sku)
        if not product_id:
            continue
        if not product.is_active:
            hidden_ids.add(product_id)
            continue
        selectable = product.get_selectable_options()
        default_option_id = selectable[0].id if selectable else None
        resolved[product_id] = {
            "product": product,
            "default_option_id": default_option_id,
        }
    return resolved, hidden_ids


def _extract_printful_category_label(item: dict) -> str:
    candidates = [
        item.get("category_label"),
        item.get("main_category"),
        item.get("main_category_name"),
        item.get("category_name"),
        item.get("type_name"),
        item.get("product_type_name"),
        item.get("type"),
        item.get("category"),
    ]
    for raw in candidates:
        if isinstance(raw, dict):
            raw = raw.get("name") or raw.get("title") or ""
        text = " ".join(str(raw or "").strip().split())
        if text:
            return text[:80]
    return ""


def _normalize_merch_color_label(value: str) -> str:
    """
    Keep swatch labels stable and short.
    """
    text = " ".join(str(value or "").strip().split())
    return text[:60]


def _guess_merch_color_from_variant_name(value: str) -> str:
    """
    Printful variant names are often like: "Black / M" or "Sport Grey / XL".
    Extract the best guess of the color segment.
    """
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""

    parts = [p.strip() for p in text.split("/") if p.strip()]
    if not parts:
        return ""

    size_tokens = {
        "xs", "s", "m", "l", "xl", "xxl",
        "2xl", "3xl", "4xl", "5xl",
        "small", "medium", "large",
        "x-large", "xx-large", "xxx-large",
    }

    for part in parts:
        low = part.lower()
        if low in size_tokens:
            continue
        if low.isdigit():
            continue
        if low.endswith("xl") and low[:-2].isdigit():
            continue
        return part[:60]

    return parts[0][:60]


def _merch_color_to_hex(label: str) -> str:
    low = (label or "").lower()
    if "black" in low:
        return "#101010"
    if "white" in low:
        return "#f3f3f3"
    if "grey" in low or "gray" in low:
        return "#bdbdbd"
    if "heather" in low or "charcoal" in low:
        return "#8f949a"
    if "navy" in low:
        return "#0b1b3a"
    if "blue" in low:
        return "#1f3b7a"
    if "red" in low or "scarlet" in low:
        return "#d50000"
    if "maroon" in low or "burgundy" in low:
        return "#5b0a0a"
    if "green" in low:
        return "#1f8a4c"
    if "olive" in low:
        return "#556b2f"
    if "tan" in low or "khaki" in low:
        return "#c2b280"
    if "brown" in low:
        return "#5c4033"
    if "orange" in low:
        return "#ff7a00"
    if "yellow" in low:
        return "#f4c430"
    if "purple" in low:
        return "#5b3fd6"
    if "pink" in low:
        return "#ff5ca8"
    if "cream" in low or "natural" in low:
        return "#e9dec8"
    return "#6c6c6c"


def _build_merch_listing_media(row: dict) -> tuple[list[str], list[dict]]:
    """
    Returns (carousel_images, color_swatches).
    Swatches are derived from variant names when Printful doesn't provide structured color fields.
    """
    fallback_image = ""
    # Prefer the product-level thumbnail (Printful "thumbnail_url") so we show the actual item
    # mockup in listings instead of a print-file preview when variant payloads vary.
    for key in ("image_url", "thumbnail_url", "thumbnail", "photo_url"):
        candidate = (row.get(key) or "").strip()
        if candidate:
            fallback_image = candidate
            break
    variants = row.get("variants") if isinstance(row.get("variants"), list) else []

    swatches: "OrderedDict[str, dict]" = OrderedDict()
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        raw_color = variant.get("color") or ""
        color = _normalize_merch_color_label(raw_color) if raw_color else ""
        if not color:
            color = _normalize_merch_color_label(
                _guess_merch_color_from_variant_name(str(variant.get("name") or ""))
            )
        if not color:
            continue

        key = color.lower()
        if key in swatches:
            continue

        # `core.services.printful` normalizes variant images into `image_url`.
        # Keep extra keys as defensive fallbacks because Printful payloads vary by store type.
        image_url = ""
        for key in ("image_url", "thumbnail_url", "preview_url"):
            candidate = (variant.get(key) or "").strip()
            if candidate:
                image_url = candidate
                break
        if not image_url:
            image_url = fallback_image
        swatches[key] = {
            "label": color,
            "hex": _merch_color_to_hex(color),
            "image_url": image_url,
        }

    # Build unique carousel images.
    # Always lead with the product thumbnail when available (prevents "blank black" print previews).
    carousel_images: list[str] = []
    seen: set[str] = set()
    if fallback_image:
        seen.add(fallback_image)
        carousel_images.append(fallback_image)
    for swatch in swatches.values():
        url = (swatch.get("image_url") or "").strip()
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        carousel_images.append(url)

    # Last-ditch: pick any variant image if both swatches and product thumbnail are empty.
    if not carousel_images:
        for variant in variants:
            candidate = (variant.get("image_url") or "").strip()
            if candidate:
                carousel_images = [candidate]
                break

    # Store an index per swatch so the template can jump the carousel.
    for swatch in swatches.values():
        url = (swatch.get("image_url") or "").strip()
        swatch["carousel_index"] = carousel_images.index(url) if url in carousel_images else 0

    # Keep the UI compact; merch variants can be large.
    swatch_list = list(swatches.values())[:8]
    return carousel_images[:8], swatch_list


def _enrich_printful_merch_products(products: list[dict]) -> list[dict]:
    if not products:
        return []

    synced, hidden_ids = _build_synced_printful_merch_map(products)
    enriched: list[dict] = []
    for item in products:
        row = dict(item or {})
        try:
            product_id = int(row.get("id") or 0)
        except (TypeError, ValueError):
            product_id = 0

        if product_id and product_id in hidden_ids:
            continue

        matched = synced.get(product_id)
        product = matched["product"] if matched else None
        if product:
            merch_category = getattr(product, "merch_category", None)
            if merch_category and getattr(merch_category, "is_active", False):
                row["merch_category_id"] = merch_category.id
                row["category_label"] = merch_category.name or ""
                row["category_key"] = merch_category.slug or ""
            else:
                row["merch_category_id"] = None
                raw_category_label = _extract_printful_category_label(row)
                if raw_category_label:
                    category_key, category_label = normalize_merch_category(raw_category_label)
                    row["category_label"] = category_label or raw_category_label
                    row["category_key"] = category_key or (slugify(raw_category_label)[:64] or f"category-{product_id}")
            row["store_product_url"] = reverse("store:store-product", kwargs={"slug": product.slug})
            row["checkout_label"] = "Choose options"
            row["url"] = row["store_product_url"]
        else:
            row["merch_category_id"] = None
            raw_category_label = _extract_printful_category_label(row)
            if raw_category_label:
                category_key, category_label = normalize_merch_category(raw_category_label)
                row["category_label"] = category_label or raw_category_label
                row["category_key"] = category_key or (slugify(raw_category_label)[:64] or f"category-{product_id}")
            row["store_product_url"] = ""
            row["checkout_label"] = "View catalog"
        carousel_images, color_swatches = _build_merch_listing_media(row)
        row["carousel_images"] = carousel_images
        row["color_swatches"] = color_swatches
        enriched.append(row)
    return enriched


def _build_store_merch_products() -> list[dict]:
    rows: list[dict] = []
    products = (
        Product.objects.filter(sku__startswith="PF-", is_active=True)
        .select_related("merch_category")
        .order_by("name")
    )
    for product in products:
        product_id = _parse_printful_product_id_from_sku(product.sku) or product.id
        image_url = ""
        if getattr(product, "main_image", None):
            try:
                image_url = product.main_image.url
            except Exception:
                image_url = ""

        merch_category = getattr(product, "merch_category", None)
        category_key = ""
        category_label = ""
        merch_category_id = None
        if merch_category and getattr(merch_category, "is_active", False):
            merch_category_id = merch_category.id
            category_label = merch_category.name or ""
            category_key = merch_category.slug or (slugify(category_label)[:64] if category_label else "")

        base_price = product.price if product.price is not None else Decimal("0.00")
        price_label = format_currency(base_price)
        store_url = reverse("store:store-product", kwargs={"slug": product.slug})

        row = {
            "id": product_id,
            "name": product.name or "",
            "category_label": category_label,
            "category_key": category_key,
            "merch_category_id": merch_category_id,
            "image_url": image_url,
            "base_price": str(base_price),
            "price_label": price_label,
            "currency": (product.currency or "").strip().upper(),
            "variants": [],
            "url": store_url,
            "store_product_url": store_url,
            "checkout_label": "Choose options",
        }
        carousel_images, color_swatches = _build_merch_listing_media(row)
        row["carousel_images"] = carousel_images
        row["color_swatches"] = color_swatches
        rows.append(row)
    return rows


class MerchPlaceholderView(TemplateView):
    template_name = "client/merch.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["merch_copy"] = MerchPageCopy.get_solo()
        printful_feed = get_printful_merch_feed()
        all_products = _enrich_printful_merch_products(printful_feed.get("products", []))
        if not all_products and printful_feed.get("error"):
            all_products = _build_store_merch_products()

        manual_categories = list(
            MerchCategory.objects.filter(is_active=True).order_by("sort_order", "name")
        )

        selected_merch_category = (self.request.GET.get("category") or "").strip()
        selected_merch_category_label = ""
        merch_categories: list[dict] = []
        merch_category_cards: list[dict] = []
        merch_display_products: list[dict] = []
        show_merch_category_grid = False
        show_merch_filters = False

        def _first_product_image(rows: list[dict]) -> str:
            for row in rows:
                carousel = row.get("carousel_images") if isinstance(row.get("carousel_images"), list) else []
                if carousel:
                    return str(carousel[0] or "").strip()
                image = str(row.get("image_url") or "").strip()
                if image:
                    return image
            return ""

        if manual_categories:
            category_map = {cat.slug: cat for cat in manual_categories if cat.slug}
            category_name_map = {cat.name.lower(): cat for cat in manual_categories if cat.name}
            category_norm_map: dict[str, MerchCategory] = {}
            for cat in manual_categories:
                key, _label = normalize_merch_category(cat.name)
                if key:
                    category_norm_map[key] = cat
            rows_by_category: dict[int, list[dict]] = {}
            for row in all_products:
                cat_id = row.get("merch_category_id")
                if cat_id:
                    rows_by_category.setdefault(cat_id, []).append(row)
                    continue

                key = (row.get("category_key") or "").strip()
                label = (row.get("category_label") or "").strip().lower()
                cat = category_map.get(key) or category_norm_map.get(key) or category_name_map.get(label)
                if cat:
                    rows_by_category.setdefault(cat.id, []).append(row)

            for rows in rows_by_category.values():
                rows.sort(key=lambda item: (item.get("name") or "").lower())

            if all_products:
                merch_category_cards.append({
                    "key": "all",
                    "label": "All merch",
                    "description": "",
                    "cover_url": _first_product_image(all_products),
                    "cover_alt": "All merch",
                    "count": len(all_products),
                    "is_all": True,
                })

            for cat in manual_categories:
                rows = rows_by_category.get(cat.id, [])
                cover_url = ""
                if getattr(cat, "cover_image", None):
                    try:
                        cover_url = cat.cover_image.url
                    except Exception:
                        cover_url = ""
                if not cover_url:
                    cover_url = _first_product_image(rows)
                merch_category_cards.append({
                    "key": cat.slug,
                    "label": cat.name,
                    "description": cat.description or "",
                    "cover_url": cover_url,
                    "cover_alt": (cat.cover_image_alt or cat.name or "Merch category").strip(),
                    "count": len(rows),
                    "is_all": False,
                })

            merch_categories = [
                {"key": cat.slug, "label": cat.name}
                for cat in manual_categories
            ]

            if selected_merch_category == "all":
                merch_display_products = all_products
                selected_merch_category_label = "All merch"
            elif selected_merch_category and selected_merch_category in category_map:
                cat = category_map[selected_merch_category]
                merch_display_products = rows_by_category.get(cat.id, [])
                if merch_display_products:
                    selected_merch_category_label = cat.name
                else:
                    selected_merch_category = ""
                    merch_display_products = all_products
                    selected_merch_category_label = ""
            else:
                selected_merch_category = ""
                merch_display_products = all_products
                selected_merch_category_label = ""

            show_merch_category_grid = not bool(selected_merch_category)
            show_merch_filters = bool(selected_merch_category)
        else:
            category_map: dict[str, str] = {}
            for row in all_products:
                key = (row.get("category_key") or "").strip()
                label = (row.get("category_label") or "").strip()
                if key and label and key not in category_map:
                    category_map[key] = label

            merch_categories = [
                {"key": key, "label": label}
                for key, label in sorted(category_map.items(), key=lambda pair: pair[1].lower())
            ]

            if selected_merch_category and selected_merch_category in category_map:
                merch_display_products = [
                    row for row in all_products if row.get("category_key") == selected_merch_category
                ]
                selected_merch_category_label = category_map.get(selected_merch_category, "")
            else:
                selected_merch_category = ""
                merch_display_products = all_products
                selected_merch_category_label = ""
            show_merch_filters = bool(merch_categories)

        ctx["header_copy"] = ctx["merch_copy"]
        ctx["printful_products"] = all_products
        ctx["merch_display_products"] = merch_display_products
        ctx["merch_has_products"] = bool(all_products)
        ctx["printful_catalog_url"] = printful_feed.get("catalog_url", "")
        ctx["merch_categories"] = merch_categories
        ctx["merch_category_cards"] = merch_category_cards
        ctx["show_merch_category_grid"] = show_merch_category_grid
        ctx["show_merch_filters"] = show_merch_filters
        ctx["selected_merch_category"] = selected_merch_category
        ctx["selected_merch_category_label"] = selected_merch_category_label
        ctx["font_settings"] = build_page_font_context(PageFontSetting.Page.MERCH)

        # If a category is selected, prefer using an actual product mockup from that category
        # for the hero media instead of the static fallback image.
        if selected_merch_category and merch_display_products:
            first = merch_display_products[0] or {}
            hero_src = ""
            if isinstance(first.get("carousel_images"), list) and first["carousel_images"]:
                hero_src = str(first["carousel_images"][0] or "").strip()
            if not hero_src:
                hero_src = str(first.get("image_url") or "").strip()
            if hero_src:
                ctx["hero_media"] = {
                    "src": hero_src,
                    "alt": str(first.get("name") or "Merch").strip() or "Merch",
                    "caption": "",
                    "location": "merch",
                }
        return ctx

# accounts/views.py
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView
from store.models import Order

class OrdersListView(LoginRequiredMixin, ListView):
    template_name = "client/orders_list.html"
    context_object_name = "orders"
    paginate_by = 20

    def get_queryset(self):
        qs = Order.objects.select_related("user").prefetch_related("orderitem_set__product").order_by("-created_at")
        # лучший вариант — по FK на пользователя
        qs_user = qs.filter(user=self.request.user)
        if qs_user.exists():
            return qs_user
        # запасной план: по email пользователя (если совпадает)
        email = getattr(self.request.user, "email", "") or ""
        if email:
            return qs.filter(email__iexact=email)
        return qs.none()

class OrderDetailView(LoginRequiredMixin, DetailView):
    template_name = "client/order_detail.html"
    model = Order
    pk_url_kwarg = "pk"

    def get_queryset(self):
        qs = super().get_queryset().select_related("user").prefetch_related("orderitem_set__product")
        # та же защита доступа
        return qs.filter(models.Q(user=self.request.user) | models.Q(email__iexact=self.request.user.email))
