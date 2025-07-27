"""
URL configuration for the *booking* project.

Routes hierarchy:
  /                 → Главное меню (только для клиентов)
  /dashboard/       → Личный кабинет клиента
  /accounts/...     → login / logout / register (accounts.urls)
  /admin/           → Django‑admin
  /autocomplete/... → Select2 endpoints
"""
from django.contrib import admin
from django.urls import path, include

from accounts.views import MainMenuView, ClientDashboardView
from core.autocomplete import ServiceAutocomplete

urlpatterns = [
    # --- Admin ---
    path("admin/", admin.site.urls),

    # --- Клиентская часть ---
    path("", MainMenuView.as_view(),          name="mainmenu"),
    path("dashboard/", ClientDashboardView.as_view(), name="client_dashboard"),

    # --- Auth / Accounts ---
    path("accounts/", include("accounts.urls")),

    # --- Autocomplete API ---
    path("autocomplete/service/",        ServiceAutocomplete.as_view(),        name="service-autocomplete"),
   
]
