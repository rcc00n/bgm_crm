# accounts/views.py
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import TemplateView, ListView
from django.views.generic.edit import CreateView

from django.utils import timezone
from django.db.models import OuterRef, Subquery, Count
from django.db.models.functions import TruncMonth

from core.models import (
    Service,
    Appointment,
    AppointmentStatusHistory,
)

from .forms import (
    ClientRegistrationForm,
    ClientProfileForm,   # ← форма профиля (должна быть определена в accounts/forms.py)
)


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

        # запасной вариант — поведение по умолчанию LoginView
        return super().get_success_url()


class RoleRequiredMixin(LoginRequiredMixin):
    """
    Миксин для ограничения доступа по конкретной роли.
    Использование:
        class SomeView(RoleRequiredMixin, TemplateView):
            required_role = "Client"
    """
    required_role: str | None = None

    def dispatch(self, request, *args, **kwargs):
        if self.required_role and not request.user.userrole_set.filter(role__name=self.required_role).exists():
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


# =========================
# Главная клиента (публичное меню)
# =========================
class MainMenuView(LoginRequiredMixin, TemplateView):
    """
    Публичный каталог услуг (главное меню для клиента) — доступ только пользователям с ролью Client.
    """
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
    Личный кабинет клиента (dashboard) с возможностью редактировать профиль.
    GET  → отдаёт страницу и данные
    POST → обрабатывает форму профиля, сохраняет User + UserProfile
    """
    template_name = "client/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        now = timezone.now()

        # профиль может отсутствовать → None
        ctx["profile"] = getattr(user, "userprofile", None)

        # для секции «Каталог/Быстрые действия» — список услуг
        ctx["services"] = Service.objects.all().order_by("name")

        # быстрый подзапрос на последний статус записи
        latest_status = (
            AppointmentStatusHistory.objects.filter(appointment_id=OuterRef("pk"))
            .order_by("-set_at")
            .values("status__name")[:1]
        )

        # все записи текущего клиента
        qs = (
            Appointment.objects
            .filter(client=user)
            .select_related("service", "master")
            .annotate(current_status=Subquery(latest_status))
            .order_by("-start_time")
        )

        ctx["appointments"] = qs
        ctx["next_appointment"] = qs.filter(start_time__gte=now).first()
        ctx["recent_appointments"] = qs.filter(start_time__lt=now)[:5]

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
        Обработка формы профиля на вкладке Profile.
        Ожидаются поля: first_name, last_name, email, phone, birth_date (YYYY-MM-DD).
        """
        form = ClientProfileForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Профиль обновлён.")
            # Вернём пользователя на вкладку Profile
            return redirect(reverse("dashboard") + "#profile")

        # В случае ошибок — отрисуем ту же страницу с сообщениями об ошибках
        ctx = self.get_context_data()
        ctx["profile_form_errors"] = form.errors
        return self.render_to_response(ctx, status=400)


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
    """
    Пагинированный список всех записей клиента.
    """
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
    """
    Регистрация клиента.
    Если запрос AJAX:
        • form_valid  → HttpResponse("OK")
        • form_invalid → JsonResponse(errors, 400)
    Иначе — стандартный redirect на страницу логина.
    """
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
        # вызывать reverse только здесь, когда URLConf уже загружен
        return f"{reverse('login')}?registered=1"
