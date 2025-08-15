# booking/urls.py
from django.contrib import admin
from django.urls import path, include
from accounts.views import HomeView
from core.autocomplete import ServiceAutocomplete
from core.views import service_search

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("autocomplete/service/", ServiceAutocomplete.as_view(), name="service-autocomplete"),

    path("", HomeView.as_view(), name="home"),  # ← главная

    path("accounts/api/services/search/", service_search, name="service-search"),
]
