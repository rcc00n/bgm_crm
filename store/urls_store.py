from django.urls import path
from . import views

urlpatterns = [
    path("", views.store_home, name="store"),                               # главная витрина
    path("category/<slug:slug>/", views.category_list, name="store-category"),
    path("p/<slug:slug>/", views.product_detail, name="store-product"),

    # корзина / оформление (на сессиях)
    path("cart/", views.cart_view, name="store-cart"),
    path("cart/add/<slug:slug>/", views.cart_add, name="store-cart-add"),
    path("cart/remove/<slug:slug>/", views.cart_remove, name="store-cart-remove"),
    path("checkout/", views.checkout, name="store-checkout"),
]
