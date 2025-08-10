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
from django.urls import path
from .views import (
    RoleBasedLoginView,
    MainMenuView,
    ClientDashboardView,
    MasterDashboardView,
    ClientAppointmentsListView,
    ClientRegisterView,
)
from core.views import client_dashboard, api_availability, api_book

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
    
    # каталог на /accounts/
    path("", client_dashboard, name="client-dashboard"),
    path("home/", client_dashboard, name="mainmenu"),

    # auth
    path("login/",  RoleBasedLoginView.as_view(),     name="login"),
    path("register/", ClientRegisterView.as_view(),   name="register"),

    # кабинеты/прочее
    path("dashboard/", ClientDashboardView.as_view(), name="dashboard"),
    path("master/", MasterDashboardView.as_view(),    name="master_dashboard"),
    path("client/appointments/", ClientAppointmentsListView.as_view(), name="client_appointments"),

    # API бронирования
    path("api/availability/", api_availability, name="api-availability"),
    path("api/book/", api_book, name="api-book"),
]
