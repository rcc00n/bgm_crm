from django.urls import path
from .views import RoleBasedLoginView, ClientDashboardView, MasterDashboardView
from .views import ClientAppointmentsListView
urlpatterns = [
    path('login/',   RoleBasedLoginView.as_view(), name='login'),
    path('client/',  ClientDashboardView.as_view(), name='client_dashboard'),
    path('master/',  MasterDashboardView.as_view(), name='master_dashboard'),
    path('client/appointments/', ClientAppointmentsListView.as_view(),
         name='client_appointments')
]

