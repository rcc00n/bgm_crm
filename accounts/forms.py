from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.utils.text import slugify
from core.models import CustomUserDisplay, UserProfile, Role
import phonenumbers
from core.validators import clean_phone

# ---------- Registration ----------
class ClientRegistrationForm(UserCreationForm):
    """
    Регистрация клиента: e-mail, телефон, (необязательный) username + пароль.
    После save():
        • создаёт UserProfile,
        • назначает роль «Client».
    """

    email = forms.EmailField(required=True, label="E-mail")

    # Визуально предзаполняем +1 и показываем формат;
    # валидацию/нормализацию делаем в clean_phone()
    phone = forms.CharField(
        max_length=20,
        label="Телефон",
        initial="+1 ",
        widget=forms.TextInput(attrs={"placeholder": "(555) 123‑4567"})
    )

    username = forms.CharField(required=False, label="Логин (можно оставить пустым)")

    class Meta:
        model = CustomUserDisplay
        fields = ("username", "email", "phone", "password1", "password2")

    # --- Validation helpers ---

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").lower().strip()
        if CustomUserDisplay.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Этот e-mail уже используется.")
        return email

    def clean_phone(self):
        raw = (self.cleaned_data.get("phone") or "").strip()

        # Оставляем только цифры и '+'
        raw = "".join(ch for ch in raw if ch.isdigit() or ch == "+")

        # Если код страны не указан — подставим +1
        if raw and not raw.startswith("+"):
            raw = "+1" + raw

        # Парсим и приводим к E.164
        try:
            parsed = phonenumbers.parse(raw, None)
        except phonenumbers.NumberParseException:
            raise forms.ValidationError("Неверный формат телефона.")
        phone_e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

        # Проверка уникальности среди профилей
        if UserProfile.objects.filter(phone=phone_e164).exists():
            raise forms.ValidationError("Этот телефон уже используется.")

        return phone_e164

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if username and CustomUserDisplay.objects.filter(username=username).exists():
            raise forms.ValidationError("Такой логин уже занят.")
        return username or None

    # --- Save ---

    def save(self, commit=True):
        user = super().save(commit=False)

        # email / username
        user.email = self.cleaned_data["email"]
        if not self.cleaned_data.get("username"):
            # генерируем из e-mail: "john@example.com" → "john"
            user.username = slugify(user.email.split("@")[0])

            # гарантируем уникальность
            suffix = 1
            base = user.username
            while CustomUserDisplay.objects.filter(username=user.username).exists():
                user.username = f"{base}{suffix}"
                suffix += 1

        if commit:
            user.save()

            # профиль
            phone = self.cleaned_data["phone"]  # уже в E.164
            UserProfile.objects.create(user=user, phone=phone)

            # роль «Client»
            client_role, _ = Role.objects.get_or_create(name="Client")
            user.userrole_set.get_or_create(role=client_role)

        return user

# ---------- Login ----------
class ClientLoginForm(AuthenticationForm):
    """
    Один input «identifier»:
        • username
        • e-mail
        • телефон
    """
    identifier = forms.CharField(label="E-mail / телефон / логин")

    # Django 5+ использует clean() вместо clean_username / clean_password
    def clean(self):
        identifier = self.cleaned_data.get("identifier")
        password = self.cleaned_data.get("password")
        self.user_cache = authenticate(self.request, username=identifier, password=password)
        if self.user_cache is None:
            raise forms.ValidationError("Неверные учётные данные.")
        self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data

# accounts/forms.py
from django import forms
from django.core.exceptions import ValidationError
from core.models import CustomUserDisplay, UserProfile
import phonenumbers

class ClientProfileForm(forms.Form):
    first_name = forms.CharField(required=False, max_length=150, label="Имя")
    last_name  = forms.CharField(required=False, max_length=150, label="Фамилия")
    email      = forms.EmailField(required=True, label="E-mail")
    phone      = forms.CharField(required=True, max_length=20, label="Телефон")
    birth_date = forms.DateField(required=False, input_formats=["%Y-%m-%d"], label="Дата рождения")

    def __init__(self, *args, **kwargs):
        self.user: CustomUserDisplay = kwargs.pop("user")
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if CustomUserDisplay.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise ValidationError("Этот e-mail уже используется.")
        return email

    def clean_phone(self):
        raw = self.cleaned_data["phone"]
        try:
            parsed = phonenumbers.parse(raw, None)
            phone_e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            raise ValidationError("Неверный формат телефона.")
        if UserProfile.objects.filter(phone=phone_e164).exclude(user=self.user).exists():
            raise ValidationError("Этот телефон уже используется.")
        return phone_e164

    def save(self):
        u = self.user
        u.first_name = self.cleaned_data.get("first_name", "") or ""
        u.last_name  = self.cleaned_data.get("last_name", "") or ""
        u.email      = self.cleaned_data["email"]
        u.save()

        prof, _ = UserProfile.objects.get_or_create(user=u)
        prof.phone      = self.cleaned_data["phone"]
        prof.birth_date = self.cleaned_data.get("birth_date")
        prof.save()
        return u
