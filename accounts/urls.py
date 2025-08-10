from django.urls import path
from .views import (
    RoleBasedLoginView,
    ClientDashboardView,
    MasterDashboardView,
    ClientAppointmentsListView,
    ClientRegisterView,
    MainMenuView,  # можно оставить, если где-то используется
)
from core.views import public_mainmenu, api_availability, api_book
from django.contrib.auth.views import LogoutView

urlpatterns = [
    # Публичная главная (каталог) для всех
    path("", public_mainmenu, name="client-dashboard"),
    path("home/", public_mainmenu, name="mainmenu"),

    # Аутентификация
    path("login/",    RoleBasedLoginView.as_view(),   name="login"),
    path("register/", ClientRegisterView.as_view(),   name="register"),

    # Личные кабинеты (как у тебя уже реализовано)
    path("dashboard/", ClientDashboardView.as_view(), name="dashboard"),
    path("master/",    MasterDashboardView.as_view(), name="master_dashboard"),
    path("client/appointments/", ClientAppointmentsListView.as_view(), name="client_appointments"),

    # API бронирования (требует логина)
    path("api/availability/", api_availability, name="api-availability"),
    path("api/book/",         api_book,         name="api-book"),
    path("logout/", LogoutView.as_view(next_page="/accounts/"), name="logout"),
]
