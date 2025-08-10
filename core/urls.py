# core/urls.py
from django.urls import path
# from core.views import ClientDashboardView
from core.views import client_dashboard
app_name = "core"

urlpatterns = [
    # личный кабинет клиента
        path("accounts/", client_dashboard, name="client-dashboard"),
]
