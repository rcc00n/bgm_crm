from django.urls import path
from .views import (
    RoleBasedLoginView,
    ClientDashboardView,
    MasterDashboardView,
    ClientAppointmentsListView,
    ClientRegisterView,
    MainMenuView,  # оставляем импорт, но маршрут на него менять не обязательно
)
from core.views import client_dashboard  # наш каталог+кабинет

urlpatterns = [
    # КАТАЛОГ: отдаём НАШУ вьюху на корень /accounts/
    path("", client_dashboard, name="client-dashboard"),

    # Дополнительно дублируем на /accounts/home/, чтобы не ломались старые ссылки
    path("home/", client_dashboard, name="mainmenu"),

    # Аутентификация / регистрация — как было
    path("login/",  RoleBasedLoginView.as_view(),     name="login"),
    path("register/", ClientRegisterView.as_view(),   name="register"),

    # Остальные страницы аккаунтов — без изменений
    path("dashboard/", ClientDashboardView.as_view(), name="dashboard"),
    path("master/", MasterDashboardView.as_view(),    name="master_dashboard"),
    path("client/appointments/", ClientAppointmentsListView.as_view(),
         name="client_appointments"),
]
