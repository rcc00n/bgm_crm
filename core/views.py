# core/views/client.py
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.db.models import Prefetch

from core.models import Appointment, UserProfile   # модели уже есть 

class ClientDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "client/mainmenu.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user

        # профиль (может не существовать, поэтому get_or_none)
        ctx["profile"] = getattr(user, "userprofile", None)

        # все записи пользователя, сразу подтягиваем связанные объекты
        ctx["appointments"] = (
            Appointment.objects
            .filter(client=user)          # поле client указывает на CustomUserDisplay :contentReference[oaicite:2]{index=2}
            .select_related("service", "master")
            .order_by("-start_time")
        )

        return ctx
