# accounts/middleware.py
from django.contrib.auth import logout

class ForceAdminReAuthMiddleware:
    """
    Разлогинивает любого аутентифицированного пользователя, пришедшего
    в /admin/ без свежего флага recent_admin_login.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)

        if request.path.startswith("/admin/") and user and user.is_authenticated:
            if not request.session.pop("recent_admin_login", False):
                logout(request)

        return self.get_response(request)
