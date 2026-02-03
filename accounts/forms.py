from __future__ import annotations

from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from django.db.models import Q

import phonenumbers

from core.models import (
    CustomUserDisplay,
    UserProfile,
    Role,
    HowHeard,  # TextChoices enumerating acquisition sources
)


# ---------- Registration ----------
class ClientRegistrationForm(UserCreationForm):
    """
    Customer registration form: email, phone, optional username, and password.
    On save it:
        - creates a UserProfile (address / how_heard / email_marketing_consent),
        - assigns the "Client" role.
    """

    email = forms.EmailField(required=True, label="E-mail")

    # Pre-fill +1 visually and show the expected format;
    # actual validation/normalization occurs in clean_phone().
    phone = forms.CharField(
        max_length=20,
        label="Phone",
        initial="+1 ",
        widget=forms.TextInput(attrs={"placeholder": "(555) 123-4567"})
    )

    username = forms.CharField(required=False, label="Username (optional)")

    # --- additional registration fields ---
    address = forms.CharField(
        required=False, label="Address",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Street, Apt, City, ZIP"})
    )

    how_heard = forms.ChoiceField(
        required=False, label="How did you hear about us?",
        choices=[("", "- Select -")] + list(HowHeard.choices)
    )

    email_marketing_consent = forms.BooleanField(
        required=False, label="News & offers"
    )

    email_product_updates = forms.BooleanField(
        required=False, label="Product drops & merch alerts"
    )

    email_service_updates = forms.BooleanField(
        required=False, label="Build updates & service reminders"
    )

    accepted_terms = forms.BooleanField(
        required=True,
        label="I AGREE",
        error_messages={
            "required": "You must accept the Terms & Conditions to create an account."
        },
    )

    class Meta:
        model = CustomUserDisplay
        fields = (
            "username", "email", "phone",
            "address", "how_heard", "email_marketing_consent",
            "email_product_updates", "email_service_updates",
            "accepted_terms",
            "password1", "password2"
        )

    # --- Validation helpers ---

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").lower().strip()
        if CustomUserDisplay.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("This email is already in use.")
        return email

    def clean_phone(self):
        raw = (self.cleaned_data.get("phone") or "").strip()
        # keep only digits and "+"
        raw = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
        # assume +1 if country code is missing
        if raw and not raw.startswith("+"):
            raw = "+1" + raw
        # parse and normalize to E.164
        try:
            parsed = phonenumbers.parse(raw, None)
        except phonenumbers.NumberParseException:
            raise forms.ValidationError("Invalid phone format.")
        phone_e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        # ensure uniqueness across profiles
        if UserProfile.objects.filter(phone=phone_e164).exists():
            raise forms.ValidationError("This phone number is already in use.")
        return phone_e164

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if username and CustomUserDisplay.objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username or None

    # --- Save ---

    def save(self, commit=True):
        user = super().save(commit=False)

        # email / username
        user.email = self.cleaned_data["email"]
        if not self.cleaned_data.get("username"):
            # derive username from email local-part
            user.username = slugify(user.email.split("@")[0])
            # ensure uniqueness
            suffix = 1
            base = user.username
            while CustomUserDisplay.objects.filter(username=user.username).exists():
                user.username = f"{base}{suffix}"
                suffix += 1

        if commit:
            user.save()

            # profile
            phone = self.cleaned_data["phone"]  # already E.164
            profile = UserProfile.objects.create(
                user=user,
                phone=phone,
                address=self.cleaned_data.get("address") or "",
                how_heard=self.cleaned_data.get("how_heard") or "",
                email_product_updates=bool(self.cleaned_data.get("email_product_updates")),
                email_service_updates=bool(self.cleaned_data.get("email_service_updates")),
            )
            # marketing consent + timestamp
            consent = bool(self.cleaned_data.get("email_marketing_consent"))
            profile.set_marketing_consent(consent)
            profile.save(update_fields=[
                "address", "how_heard",
                "email_marketing_consent", "email_marketing_consented_at",
                "email_product_updates", "email_service_updates",
            ])

            # assign Client role
            client_role, _ = Role.objects.get_or_create(name="Client")
            user.userrole_set.get_or_create(role=client_role)

        return user


# ---------- Login ----------
class ClientLoginForm(AuthenticationForm):
    """
    Single "identifier" input:
        - username
        - e-mail
        - phone number
    (Update the login template to use {{ form.identifier }} and {{ form.password }} when wiring this form.)
    """
    identifier = forms.CharField(label="Email / phone / username")

    def clean(self):
        identifier = self.cleaned_data.get("identifier")
        password = self.cleaned_data.get("password")
        self.user_cache = authenticate(self.request, username=identifier, password=password)
        if self.user_cache is None:
            raise forms.ValidationError("Incorrect credentials.")
        self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data


# ---------- Login with email verification ----------
class VerifiedLoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        self.unverified_user = None
        super().__init__(*args, **kwargs)

    def _raise_unverified_if_needed(self, identifier: str) -> None:
        UserModel = get_user_model()
        user = UserModel.objects.filter(
            Q(username=identifier)
            | Q(email__iexact=identifier)
            | Q(userprofile__phone=identifier)
        ).first()
        if user and not user.is_staff and not user.is_superuser:
            profile = getattr(user, "userprofile", None)
            if profile and not profile.email_verified_at:
                self.unverified_user = user
                raise forms.ValidationError(
                    "Please verify your email before signing in.",
                    code="email_unverified",
                )

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if username is not None and password:
            self.user_cache = authenticate(self.request, username=username, password=password)
            if self.user_cache is None:
                self._raise_unverified_if_needed(username)
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data

    def confirm_login_allowed(self, user):
        profile = getattr(user, "userprofile", None)
        if profile and not profile.email_verified_at and not user.is_staff and not user.is_superuser:
            self.unverified_user = user
            raise forms.ValidationError(
                "Please verify your email before signing in.",
                code="email_unverified",
            )
        super().confirm_login_allowed(user)


# ---------- Profile edit ----------
class ClientProfileForm(forms.Form):
    first_name = forms.CharField(required=False, max_length=150, label="First name")
    last_name  = forms.CharField(required=False, max_length=150, label="Last name")
    email      = forms.EmailField(required=True, label="E-mail")
    phone      = forms.CharField(required=True, max_length=20, label="Phone")
    birth_date = forms.DateField(required=False, input_formats=["%Y-%m-%d"], label="Birth date")

    # --- profile extras ---
    address = forms.CharField(
        required=False, label="Address",
        widget=forms.Textarea(attrs={"rows": 2})
    )
    how_heard = forms.ChoiceField(
        required=False, label="How did you hear about us?",
        choices=[("", "- Select -")] + list(HowHeard.choices)
    )
    email_marketing_consent = forms.BooleanField(
        required=False, label="News & offers"
    )
    email_product_updates = forms.BooleanField(
        required=False, label="Product drops & merch alerts"
    )
    email_service_updates = forms.BooleanField(
        required=False, label="Build updates & service reminders"
    )

    def __init__(self, *args, **kwargs):
        self.user: CustomUserDisplay = kwargs.pop("user")
        super().__init__(*args, **kwargs)

        # pre-fill current profile values when rendering GET form
        try:
            prof = self.user.userprofile
            self.fields["phone"].initial = prof.phone
            self.fields["birth_date"].initial = prof.birth_date
            self.fields["address"].initial = prof.address
            self.fields["how_heard"].initial = prof.how_heard
            self.fields["email_marketing_consent"].initial = prof.email_marketing_consent
            self.fields["email_product_updates"].initial = prof.email_product_updates
            self.fields["email_service_updates"].initial = prof.email_service_updates
        except UserProfile.DoesNotExist:
            pass

        self.fields["first_name"].initial = self.user.first_name
        self.fields["last_name"].initial = self.user.last_name
        self.fields["email"].initial = self.user.email

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").lower().strip()
        if CustomUserDisplay.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise ValidationError("This email is already in use.")
        return email

    def clean_phone(self):
        raw = (self.cleaned_data.get("phone") or "").strip()
        # normalize to E.164 with default +1
        raw = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
        if raw and not raw.startswith("+"):
            raw = "+1" + raw
        try:
            parsed = phonenumbers.parse(raw, None)
            phone_e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            raise ValidationError("Invalid phone format.")
        # ensure uniqueness excluding the current user
        qs = UserProfile.objects.filter(phone=phone_e164)
        qs = qs.exclude(user=self.user)
        if qs.exists():
            raise ValidationError("This phone number is already in use.")
        return phone_e164

    def save(self):
        u = self.user
        u.first_name = self.cleaned_data.get("first_name", "") or ""
        u.last_name  = self.cleaned_data.get("last_name", "") or ""
        u.email      = self.cleaned_data["email"]
        u.save(update_fields=["first_name", "last_name", "email"])

        prof, _ = UserProfile.objects.get_or_create(user=u)
        prof.phone      = self.cleaned_data["phone"]              # already E.164
        prof.birth_date = self.cleaned_data.get("birth_date") or None
        prof.address    = self.cleaned_data.get("address", "") or ""
        prof.how_heard  = self.cleaned_data.get("how_heard", "") or ""

        # consent + timestamp via model helper
        consent = bool(self.cleaned_data.get("email_marketing_consent"))
        prof.set_marketing_consent(consent)
        prof.email_product_updates = bool(self.cleaned_data.get("email_product_updates"))
        prof.email_service_updates = bool(self.cleaned_data.get("email_service_updates"))

        prof.save(update_fields=[
            "phone", "birth_date", "address", "how_heard",
            "email_marketing_consent", "email_marketing_consented_at",
            "email_product_updates", "email_service_updates",
        ])
        return u
