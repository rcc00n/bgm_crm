# accounts/views.py
from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.contrib.auth.tokens import default_token_generator
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
from django.db.models import OuterRef, Subquery, Count
from django.db.models.functions import TruncMonth
from django.conf import settings
from django.template.defaultfilters import filesizeformat
import os

from core.models import (
    Service,
    Appointment,
    AppointmentStatusHistory,
    ClientFile,
    ClientPortalPageCopy,
    MerchPageCopy,
    PageFontSetting,
)
from core.services.fonts import build_page_font_context
from core.services.media import build_home_gallery_media
from core.emails import build_email_html, send_html_email
from core.email_templates import email_brand_name, join_text_sections

from .forms import (
    ClientRegistrationForm,
    ClientProfileForm,
    VerifiedLoginForm,
)

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

        # статистика по месяцам (для графика)
        month_counts = (
            qs.filter(start_time__year=now.year)
              .annotate(month=TruncMonth("start_time"))
              .values("month")
              .annotate(cnt=Count("id"))
              .order_by("month")
        )
        ctx["chart_labels"] = [m["month"].strftime("%b") for m in month_counts]
        ctx["chart_data"] = [m["cnt"] for m in month_counts]

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
from core.models import Service, ServiceCategory, HomePageCopy, ProjectJournalEntry   # ваши модели услуг
from core.services.page_layout import build_layout_styles
from store.models import Product                    # товары


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

class HomeView(TemplateView):
    template_name = "client/bgm_home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["font_settings"] = build_page_font_context(PageFontSetting.Page.HOME)
        home_copy = HomePageCopy.get_solo()
        ctx["home_copy"] = home_copy
        ctx["layout_styles"] = build_layout_styles(HomePageCopy, home_copy.layout_overrides)
        # это у вас уже есть:
        ctx["categories"] = ServiceCategory.objects.all()
        ctx["filter_categories"] = ctx["categories"]
        ctx["uncategorized"] = Service.objects.filter(category__isnull=True)
        ctx["has_any_services"] = Service.objects.exists()

        # НОВОЕ: 8 услуг для главной (витрина)
        ctx["home_services"] = (
            Service.objects.select_related("category")
            .order_by("-id")[:8]
        )

        # НОВОЕ: 8 товаров для главной (витрина)
        products_qs = (
            Product.objects.filter(is_active=True)
            .select_related("category")
            .prefetch_related("options")
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
        gallery_items = [
            {
                "src": post.cover_image.url,
                "alt": post.hero_title or post.title,
                "title": post.hero_title or post.title,
                "caption": post.result_highlight or post.excerpt,
                "url": post.get_absolute_url(),
            }
            for post in gallery_posts
        ]
        if len(gallery_items) < 4:
            for asset in build_home_gallery_media():
                if len(gallery_items) >= 4:
                    break
                gallery_items.append(
                    {
                        "src": asset["src"],
                        "alt": asset.get("alt") or "",
                        "title": asset.get("title") or "",
                        "caption": asset.get("caption") or "",
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


class MerchPlaceholderView(TemplateView):
    template_name = "client/merch.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["merch_copy"] = MerchPageCopy.get_solo()
        ctx["header_copy"] = ctx["merch_copy"]
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
