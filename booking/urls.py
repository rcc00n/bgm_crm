# booking/urls.py
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from accounts.views import HomeView, MerchPlaceholderView
from core.autocomplete import ServiceAutocomplete
from core.views import service_search

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),

    # Accounts
    path("accounts/", include("accounts.urls")),

    # Home
    path("", HomeView.as_view(), name="home"),

    # Autocomplete & API
    path("autocomplete/service/", ServiceAutocomplete.as_view(), name="service-autocomplete"),
    path("accounts/api/services/search/", service_search, name="service-search"),

    # === Store: основное подключение c namespace ===
    path("store/", include(("store.urls_store", "store"), namespace="store")),

    # === Алиасы для обратной совместимости (старые имена без namespace) ===
    # Главная магазина
    path("store/", RedirectView.as_view(pattern_name="store:store", permanent=False), name="store"),
    # Корзина
    path("store/cart/", RedirectView.as_view(pattern_name="store:store-cart", permanent=False), name="store-cart"),
    # Checkout
    path("store/checkout/", RedirectView.as_view(pattern_name="store:store-checkout", permanent=False), name="store-checkout"),
    # Категория
    path(
        "store/category/<slug:slug>/",
        RedirectView.as_view(pattern_name="store:store-category", permanent=False),
        name="store-category",
    ),
    # Карточка товара
    path(
        "store/p/<slug:slug>/",
        RedirectView.as_view(pattern_name="store:store-product", permanent=False),
        name="store-product",
    ),
    # Корзина: добавить/удалить
    path(
        "store/cart/add/<slug:slug>/",
        RedirectView.as_view(pattern_name="store:store-cart-add", permanent=False),
        name="store-cart-add",
    ),
    path(
        "store/cart/remove/<slug:slug>/",
        RedirectView.as_view(pattern_name="store:store-cart-remove", permanent=False),
        name="store-cart-remove",
    ),

    # Merch (заглушка)
    path("merch/", MerchPlaceholderView.as_view(), name="merch"),
]
