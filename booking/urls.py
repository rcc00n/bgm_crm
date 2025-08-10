"""
URL configuration for the booking project.

Routes:
  /admin/                 → Django admin
  /accounts/              → модуль аккаунтов (login/register/dashboard/...) + каталог (на корне)
  /autocomplete/...       → Select2 endpoints
"""
from django.contrib import admin
from django.urls import path, include
from core.autocomplete import ServiceAutocomplete

urlpatterns = [
    path("admin/", admin.site.urls),

    # ВАЖНО: подключаем accounts БЕЗ namespace, чтобы {% url 'register' %} и т.п. работали
    path("accounts/", include("accounts.urls")),

    path("autocomplete/service/", ServiceAutocomplete.as_view(), name="service-autocomplete"),

    # Ничего из core тут не монтируем, чтобы не перехватывать /accounts/
]
