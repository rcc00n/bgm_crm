# accounts/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm
from core.models import CustomUserDisplay, UserProfile, Role

class ClientRegistrationForm(UserCreationForm):
    """
    Облегчённая форма: логин, e-mail, телефон + пароль.
    При save() создаём профиль и роль 'Client'.
    """
    email = forms.EmailField(required=True, label="E-mail")
    phone = forms.CharField(max_length=20, label="Телефон")

    class Meta:
        model = CustomUserDisplay
        fields = ("username", "email", "phone", "password1", "password2")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
            # профиль
            UserProfile.objects.create(user=user, phone=self.cleaned_data["phone"])
            # роль Client
            client_role, _ = Role.objects.get_or_create(name="Client")
            user.userrole_set.create(role=client_role)
        return user
