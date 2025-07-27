# booking/urls.py
from django.contrib import admin
from django.urls import path, include
from core.autocomplete import ServiceAutocomplete
from accounts.views import MainMenuView, ClientDashboardView   # ← ваши CBV

urlpatterns = [
    # — административный раздел —
    path('admin/', admin.site.urls),

    # — клиентская часть —
    path('', MainMenuView.as_view(),            name='mainmenu'),        # главное меню
    path('dashboard/', ClientDashboardView.as_view(), name='client_dashboard'),  # личный кабинет

    # — аутентификация —
    path('accounts/', include('accounts.urls')),  # login / logout / password-reset и т.д.

    # — autocomplete —
    path('autocomplete/service/',        ServiceAutocomplete.as_view(),        name='service-autocomplete'),

]
