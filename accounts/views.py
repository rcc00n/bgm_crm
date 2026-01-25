# accounts/views.py
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse, HttpResponse
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import TemplateView, ListView
from django.views.generic.edit import CreateView

from django.utils import timezone
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
    PageFontSetting,
)
from core.services.fonts import build_page_font_context

from .forms import (
    ClientRegistrationForm,
    ClientProfileForm,
)

CLIENT_PORTAL_FILE_MAX_MB = getattr(settings, "CLIENT_PORTAL_FILE_MAX_MB", 10)
CLIENT_PORTAL_FILE_MAX_BYTES = CLIENT_PORTAL_FILE_MAX_MB * 1024 * 1024
CLIENT_PORTAL_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf"}
CLIENT_PORTAL_ALLOWED_MIME_TYPES = {"application/pdf"}

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


class RoleRequiredMixin(LoginRequiredMixin):
    """
    Ограничение доступа по конкретной роли.
    """
    required_role: str | None = None

    def dispatch(self, request, *args, **kwargs):
        if self.required_role and not request.user.userrole_set.filter(role__name=self.required_role).exists():
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


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
        form.save()
        if self.request.headers.get("x-requested-with") == "XMLHttpRequest":
            return HttpResponse("OK")
        return super().form_valid(form)

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
from core.models import Service, ServiceCategory   # ваши модели услуг
from store.models import Product                    # товары


def _select_home_products(
    products_qs,
    *,
    limit: int = 8,
    in_house_target: int = 2,
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
        ctx["home_products"] = _select_home_products(products_qs, limit=8, in_house_target=2)
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
