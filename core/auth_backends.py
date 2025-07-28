from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from core.models import UserProfile

User = get_user_model()

class EmailPhoneBackend(ModelBackend):
    """
    Позволяет войти по username, e-mail или телефону.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        # 1) username
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            # 2) e-mail
            try:
                user = User.objects.get(email__iexact=username)
            except User.DoesNotExist:
                # 3) телефон
                try:
                    profile = UserProfile.objects.select_related("user").get(phone=username)
                    user = profile.user
                except UserProfile.DoesNotExist:
                    return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
