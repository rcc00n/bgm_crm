from django.contrib.auth.views import LoginView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.urls import reverse
from core.models import Role
from core.models import Service
from django.views.generic.edit import CreateView
from django.urls import reverse_lazy
from .forms import ClientRegistrationForm
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest



class RoleBasedLoginView(LoginView):
    template_name = 'registration/login.html'  # путь совпадает с Django-вским стандартом

    def get_success_url(self):
        user = self.request.user
        if user.is_staff or user.is_superuser:          # админ → /admin
            return reverse('admin:index')

        # Получаем роли одним запросом
        role_names = set(
            user.userrole_set.select_related('role')
                .values_list('role__name', flat=True)
        )
        if 'Master' in role_names:
            return reverse('master_dashboard')
        if 'Client' in role_names:
            return reverse('mainmenu')

        # запасной вариант
        return super().get_success_url()


class RoleRequiredMixin(LoginRequiredMixin):
    """Базовый миксин для проверки конкретной роли."""
    required_role: str = None

    def dispatch(self, request, *args, **kwargs):
        if self.required_role and \
           self.required_role not in request.user.userrole_set.values_list('role__name', flat=True):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class MainMenuView(LoginRequiredMixin, TemplateView):
    """
    Главное меню после логина.
    """
    template_name = "client/mainmenu.html"


class ClientDashboardView(LoginRequiredMixin, TemplateView):
    """
    Личный кабинет клиента («дешборд»).
    Пока выводим каталог услуг заглушкой.
    """
    template_name = "client/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["services"] = Service.objects.all().order_by("name")  # позже добавим фильтры
        return ctx


class MasterDashboardView(RoleRequiredMixin, TemplateView):
    required_role = 'Master'
    template_name = 'master/dashboard.html'

# accounts/views.py
from django.views.generic import ListView
from core.models import Appointment

class ClientAppointmentsListView(RoleRequiredMixin, ListView):
    required_role = 'Client'
    model = Appointment
    template_name = 'client/appointments_list.html'
    paginate_by = 10

    def get_queryset(self):
        return (Appointment.objects
                .filter(client=self.request.user)
                .select_related('service')
                .order_by('-start_time'))

# accounts/views.py
from django.views.generic import TemplateView
# RoleRequiredMixin уже должен быть объявлен выше в этом же файле

class MainMenuView(RoleRequiredMixin, TemplateView):
    required_role = 'Client'            # пускаем только клиентов
    template_name = "client/mainmenu.html"


# accounts/views.py
from django.urls import reverse
from django.http import JsonResponse, HttpResponse
from django.views.generic.edit import CreateView
from .forms import ClientRegistrationForm

class ClientRegisterView(CreateView):
    form_class = ClientRegistrationForm
    template_name = "registration/register_popup.html"   # запасной шаблон
    success_url = None                                   # ❶ ничего здесь!

    # ---------- успешный POST ----------
    def form_valid(self, form):
        form.save()
        if self.request.headers.get("x-requested-with") == "XMLHttpRequest":
            return HttpResponse("OK")
        return super().form_valid(form)

    # ---------- ошибки валидации ----------
    def form_invalid(self, form):
        if self.request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(form.errors, status=400)
        return super().form_invalid(form)

    # ---------- куда редиректить при обычном POST ----------
    def get_success_url(self):
        # ❷ reverse вызывается ТОЛЬКО сейчас, когда URL-ы уже загружены
        return f"{reverse('login')}?registered=1"
