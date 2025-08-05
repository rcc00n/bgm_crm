# core/urls.py
from django.urls import path
from core.views import ClientDashboardView

app_name = "core"

urlpatterns = [
    # личный кабинет клиента
    path("accounts/", ClientDashboardView.as_view(), name="client-dashboard"),
]
