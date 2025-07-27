from django.urls import path
from .views import RoleBasedLoginView, ClientDashboardView, MasterDashboardView
from .views import ClientAppointmentsListView, MainMenuView, ClientDashboardView, ClientRegisterView
urlpatterns = [
    path('login/',   RoleBasedLoginView.as_view(), name='login'),
    path("", MainMenuView.as_view(), name="mainmenu"),                 # ← после логина сюда
    path("dashboard/", ClientDashboardView.as_view(), name="dashboard"),
    path('master/',  MasterDashboardView.as_view(), name='master_dashboard'),
    path('client/appointments/', ClientAppointmentsListView.as_view(),
         name='client_appointments'),
    path("register/", ClientRegisterView.as_view(), name="register"),
    

]

