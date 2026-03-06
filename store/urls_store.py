from django.urls import path
from . import views

app_name = "store"

urlpatterns = [
    path("", views.store_home, name="store"),
    path("api/products/search/", views.product_search, name="product-search"),
    path("category/<slug:slug>/", views.category_list, name="store-category"),
    path("p/<slug:slug>/", views.product_detail, name="store-product"),
    path("cart/", views.cart_view, name="store-cart"),
    path("cart/add/<slug:slug>/", views.cart_add, name="store-cart-add"),
    path("cart/remove/<slug:slug>/", views.cart_remove, name="store-cart-remove"),
    path("cart/promo/", views.cart_promo, name="store-cart-promo"),
    path("checkout/printful-shipping-rates/", views.checkout_printful_rates, name="store-checkout-printful-rates"),
    path("checkout/", views.checkout, name="store-checkout"),
    path("printful/webhook/<str:secret>/", views.printful_webhook, name="store-printful-webhook"),
]
