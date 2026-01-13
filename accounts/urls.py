# urls_accounts.py (accounts_folder)
from django.urls import path
from django.contrib.auth.views import LogoutView
from django.urls import reverse_lazy  # ← ДОБАВИЛИ

from .views import (
    RoleBasedLoginView,
    ClientDashboardView,
    MasterDashboardView,
    ClientAppointmentsListView,
    ClientRegisterView,
    MainMenuView,
    ClientFileUploadView,
    ClientFileDeleteView,
)
from core.views import (
    public_mainmenu, api_availability, api_book,
    api_appointment_cancel, api_appointment_reschedule,
)
from .views import OrdersListView, OrderDetailView

urlpatterns = [
    # Публичная главная (каталог) под префиксом /accounts/ — без изменений
    path("", public_mainmenu, name="client-dashboard"),
    path("home/", public_mainmenu, name="mainmenu"),

    # Аутентификация
    path("login/",    RoleBasedLoginView.as_view(),   name="login"),
    path("register/", ClientRegisterView.as_view(),   name="register"),
    path(
        "logout/",
        LogoutView.as_view(next_page=reverse_lazy("home")),  # ← БЫЛО "/home/", СТАЛО reverse_lazy
        name="logout",
    ),

    # ЛК и API — без изменений
    path("dashboard/", ClientDashboardView.as_view(), name="dashboard"),
    path("dashboard/files/upload/", ClientFileUploadView.as_view(), name="dashboard-file-upload"),
    path("dashboard/files/<uuid:file_id>/delete/", ClientFileDeleteView.as_view(), name="dashboard-file-delete"),
    path("master/",    MasterDashboardView.as_view(), name="master_dashboard"),
    path("client/appointments/", ClientAppointmentsListView.as_view(), name="client_appointments"),

    path("api/availability/", api_availability, name="api-availability"),
    path("api/book/",         api_book,         name="api-book"),
    path("api/appointment/<uuid:appt_id>/cancel/",     api_appointment_cancel,     name="api-appt-cancel"),
    path("api/appointment/<uuid:appt_id>/reschedule/", api_appointment_reschedule, name="api-appt-reschedule"),
    
    path("dashboard/orders/", OrdersListView.as_view(), name="dashboard-orders"),
    path("dashboard/orders/<uuid:pk>/", OrderDetailView.as_view(), name="dashboard-order"),
]
