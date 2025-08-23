# urls_booking.py (booking_folder)
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView  # ← ДОБАВИЛИ
from accounts.views import HomeView, MerchPlaceholderView
from core.autocomplete import ServiceAutocomplete
from core.views import service_search

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),

    path("", HomeView.as_view(), name="home"),  # главная
    path("home/", RedirectView.as_view(pattern_name="home", permanent=False)),  # ← /home → home

    path("autocomplete/service/", ServiceAutocomplete.as_view(), name="service-autocomplete"),
    path("accounts/api/services/search/", service_search, name="service-search"),

    # магазин подключаем целиком
    path("store/", include("store.urls_store")),

    path("merch/", MerchPlaceholderView.as_view(), name="merch"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
