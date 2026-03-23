import re
from decimal import Decimal

from dal import autocomplete
from django import forms
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from .models import *
from .constants import STAFF_DISPLAY_NAME
from core.utils import get_staff_queryset
from core.validators import clean_phone
from core.services.admin_notifications import (
    get_notification_group_choices,
    get_notification_group_keys,
)


class MultipleFileInput(forms.ClearableFileInput):
    """
    ClearableFileInput variant that allows selecting multiple files.
    """
    allow_multiple_selected = True


STAFF_ROLE_NAMES = {"Admin", "Master"}


def _ordered_role_queryset():
    return Role.objects.order_by("name")


def _sync_user_roles(user, roles):
    roles = list(roles)
    selected_ids = {role.pk for role in roles if role.pk}
    UserRole.objects.filter(user=user).exclude(role_id__in=selected_ids).delete()
    for role in roles:
        UserRole.objects.get_or_create(user=user, role=role)


def _promote_staff_access_for_roles(user, roles):
    if user.is_superuser or any(role.name in STAFF_ROLE_NAMES for role in roles):
        user.is_staff = True

# -----------------------------
# Font settings
# -----------------------------


class PageFontSettingAdminForm(forms.ModelForm):
    """
    Admin-facing form that limits selectable fonts to active presets and
    provides clear guidance on where each choice is applied.
    """

    class Meta:
        model = PageFontSetting
        fields = ["page", "body_font", "heading_font", "ui_font", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active_fonts = FontPreset.objects.filter(is_active=True).order_by("name")
        for field_name in ("body_font", "heading_font", "ui_font"):
            if field_name in self.fields:
                self.fields[field_name].queryset = active_fonts
        if "body_font" in self.fields:
            self.fields["body_font"].label = "Body font"
            self.fields["body_font"].help_text = "Paragraphs, form inputs, and most UI copy."
        if "heading_font" in self.fields:
            self.fields["heading_font"].label = "Heading font"
            self.fields["heading_font"].help_text = "Hero and section headings."
        if "ui_font" in self.fields:
            self.fields["ui_font"].label = "UI font (optional)"
            self.fields["ui_font"].help_text = "Overrides nav/buttons if provided; otherwise inherits the body font."
        if "page" in self.fields:
            self.fields["page"].help_text = "Pick the public page that should use these fonts."

    def clean(self):
        cleaned = super().clean()
        body_font = cleaned.get("body_font")
        heading_font = cleaned.get("heading_font")
        ui_font = cleaned.get("ui_font") or body_font
        if not body_font:
            raise forms.ValidationError("Body font is required.")
        if not heading_font:
            raise forms.ValidationError("Heading font is required.")
        cleaned["ui_font"] = ui_font
        return cleaned

# -----------------------------
# Appointment Form
# -----------------------------

class AppointmentForm(forms.ModelForm):
    """
    Custom form for the Appointment model.
    Adds autocomplete functionality for the 'service' field.
    """
    status = forms.ModelChoiceField(
        queryset=AppointmentStatus.objects.all(),
        required=True,
        label="Appointment status"
    )
    promocode = forms.CharField(required=False, label="Promocode")
    class Meta:
        model = Appointment
        fields = '__all__'
        widgets = {
            'service': autocomplete.ModelSelect2(url='service-autocomplete')
        }
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        master_field = self.fields.get("master")
        if master_field:
            master_field.label = STAFF_DISPLAY_NAME
        if self.instance and getattr(self.instance, "pk", None):
            try:
                appt_promo = self.instance.appointmentpromocode
            except AppointmentPromoCode.DoesNotExist:
                appt_promo = None
            if appt_promo:
                self.fields["promocode"].initial = appt_promo.promocode.code

    def clean(self):
        cleaned_data = super().clean()
        client_obj = cleaned_data.get("client")

        if client_obj:
            contact_name = (cleaned_data.get("contact_name") or "").strip()
            if not contact_name:
                contact_name = (
                    client_obj.get_full_name()
                    or client_obj.username
                    or client_obj.email
                    or ""
                )
                cleaned_data["contact_name"] = contact_name

            contact_email = (cleaned_data.get("contact_email") or "").strip()
            if not contact_email and client_obj.email:
                cleaned_data["contact_email"] = client_obj.email

            if not (cleaned_data.get("contact_phone") or "").strip():
                profile = getattr(client_obj, "userprofile", None)
                phone = getattr(profile, "phone", "") if profile else ""
                if phone:
                    cleaned_data["contact_phone"] = phone

        instance = self.instance

        # Обнови instance перед вызовом clean()
        # Keep the model instance in sync so Appointment.clean() validates actual form data.
        for field in (
            "client",
            "contact_name",
            "contact_email",
            "contact_phone",
            "master",
            "service",
            "start_time",
            "payment_status",
        ):
            if field in cleaned_data:
                setattr(instance, field, cleaned_data.get(field))
        promocode_str = (cleaned_data.get("promocode") or "").strip()
        cleaned_data["promocode"] = promocode_str
        service = cleaned_data.get("service")
        try:
            instance.clean()
        except ValidationError as e:
            raise forms.ValidationError(e)

        if promocode_str:
            try:
                code = PromoCode.objects.get(code__iexact=promocode_str)
                if not code.is_valid_for_service(service):
                    raise forms.ValidationError("This promo code is not valid for the selected service or date.")
                today = timezone.now().date()
                if ServiceDiscount.objects.filter(
                    service=service,
                    start_date__lte=today,
                    end_date__gte=today,
                ).exists():
                    raise forms.ValidationError("This service already has a discount. Promo code can't be applied.")
                cleaned_data["applied_promocode"] = code
            except PromoCode.DoesNotExist:
                raise forms.ValidationError("Promo code not found.")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.save()

        promocode = self.cleaned_data.get("applied_promocode")
        if promocode:
            base_amount = instance.service.base_price_amount()
            percent = Decimal(promocode.discount_percent) / Decimal("100")
            discount = (base_amount * percent).quantize(Decimal("0.01"))
            AppointmentPromoCode.objects.update_or_create(
                appointment=instance,
                defaults={
                    "promocode": promocode,
                    "discount_applied": discount,
                },
            )
        else:
            AppointmentPromoCode.objects.filter(appointment=instance).delete()

        new_status = self.cleaned_data['status']

        latest = instance.appointmentstatushistory_set.order_by('-set_at').first()
        if not latest or latest.status != new_status:
            AppointmentStatusHistory.objects.create(
                appointment=instance,
                status=new_status,
                set_by=self.user
            )

        return instance

# -----------------------------
# Custom User Creation Form
# -----------------------------

class CustomUserCreationForm(UserCreationForm):
    """
    Custom user creation form with additional fields:
    - Email, phone, birth date, and roles
    - Automatically creates and links a UserProfile
    - Assigns roles after saving the user
    """
    email = forms.EmailField(required=True)
    first_name = forms.CharField(required=True)
    last_name = forms.CharField(required=True)
    phone = forms.CharField(required=True)
    birth_date = forms.DateField(required=False, widget=forms.SelectDateWidget(years=range(1950, 2030)))
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Pick one or more roles. If nothing is selected, the user will be created as Client.",
    )


    class Meta:
        model = User
        fields = [
            'username', 'email', 'first_name', 'last_name',
            'phone', 'birth_date',
            'password1', 'password2',
            'is_staff', 'is_active', 'is_superuser',
            'groups'
        ]

    def save(self, commit=True):
        """
        Overridden save method to:
        - Set password
        - Create and populate UserProfile
        - Assign roles to the new user
        """
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        selected_roles = list(self.cleaned_data.get("roles") or [])
        if not selected_roles:
            client_role, _ = Role.objects.get_or_create(name="Client")
            selected_roles = [client_role]
        _promote_staff_access_for_roles(user, selected_roles)
        user.save()

        # Create or update UserProfile
        phone = self.cleaned_data.get('phone')
        birth_date = self.cleaned_data.get('birth_date')
        profile, created = UserProfile.objects.get_or_create(user=user)
        profile.phone = phone
        profile.birth_date = birth_date
        profile.save()

        _sync_user_roles(user, selected_roles)

        return user

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["roles"].queryset = _ordered_role_queryset()
        if not self.is_bound:
            client_role = Role.objects.filter(name="Client").first()
            if client_role:
                self.fields["roles"].initial = [client_role.pk]

    def clean(self):
        return super().clean()

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if UserProfile.objects.filter(phone=phone).exists():
            raise forms.ValidationError("User with such phone number already exists.")
        return phone
# -----------------------------
# Custom User Change Form
# -----------------------------

class CustomUserChangeForm(UserChangeForm):
    """
    Custom form for editing existing users in the admin.
    - Pre-fills UserProfile fields (phone, birth_date)
    - Allows role selection and syncs them on save
    """
    password = ReadOnlyPasswordHashField(label="Password")
    email = forms.EmailField(required=True)
    first_name = forms.CharField(required=False)
    last_name = forms.CharField(required=False)
    phone = forms.CharField(required=True)
    birth_date = forms.DateField(required=False, widget=forms.SelectDateWidget(years=range(1950, 2030)))
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Assign roles directly from the user profile card.",
    )
    admin_notification_sections = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Admin notification sections",
        help_text="Toggle which admin notification sections are enabled for this staff member.",
    )


    files = forms.FileField(
        required=False,
        widget=MultipleFileInput(attrs={'multiple': True}),
        label="Upload files",
        help_text="Attach one or more files to this profile."
    )
    class Meta:
        model = User
        fields = [
            'username',
            'email',
            'first_name',
            'last_name',
            'is_staff',
            'is_active',
            'is_superuser',
            'groups',
            'user_permissions',
            'password',
            'files'
        ]

    def __init__(self, *args, **kwargs):
        """
        Populate form with data from related UserProfile and UserRole
        """
        super().__init__(*args, **kwargs)

        choices = get_notification_group_choices()
        self.fields["admin_notification_sections"].choices = choices
        self.fields["roles"].queryset = _ordered_role_queryset()

        if self.instance and hasattr(self.instance, 'userprofile'):
            self.fields['phone'].initial = self.instance.userprofile.phone
            self.fields['birth_date'].initial = self.instance.userprofile.birth_date
            disabled = set(self.instance.userprofile.admin_notification_disabled_sections or [])
            all_keys = [key for key, _ in choices]
            enabled = [key for key in all_keys if key not in disabled]
            self.fields["admin_notification_sections"].initial = enabled
        if self.instance and self.instance.pk:
            self.fields["roles"].initial = list(
                self.instance.userrole_set.values_list("role_id", flat=True)
            )


    def save(self, commit=True):
        """
        Overridden save method to:
        - Save UserProfile data
        - Sync UserRole assignments
        """
        user = super().save(commit=False)
        selected_roles = list(self.cleaned_data.get("roles") or [])
        _promote_staff_access_for_roles(user, selected_roles)
        user.save()

        # Update profile
        phone = self.cleaned_data.get('phone', '')
        birth_date = self.cleaned_data.get('birth_date', None)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.phone = phone
        profile.birth_date = birth_date
        selected_sections = set(self.cleaned_data.get("admin_notification_sections", []))
        all_sections = set(get_notification_group_keys())
        profile.admin_notification_disabled_sections = sorted(all_sections - selected_sections)
        profile.save()

        _sync_user_roles(user, selected_roles)

        uploaded_files = self.files.getlist('files')
        for f in uploaded_files:
            ClientFile.objects.create(
                user=user,
                file=f,
                uploaded_by=ClientFile.ADMIN,
                description="Uploaded via admin panel"
            )
        return user

    def clean(self):
        return super().clean()

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        qs = UserProfile.objects.filter(phone=phone)
        if self.instance.pk:
            qs = qs.exclude(user=self.instance)
        if qs.exists():
            raise forms.ValidationError("User with such phone number already exists.")
        return phone


class ServiceMasterAdminForm(forms.ModelForm):
    services = forms.ModelMultipleChoiceField(
        queryset=Service.objects.none(),
        required=False,
        widget=FilteredSelectMultiple("Services", is_stacked=False),
        help_text="Pick one or more services. Saving replaces the full assignment set for this staff member.",
    )
    assign_all_services = forms.BooleanField(
        required=False,
        label="Assign all current services",
        help_text="Ignores the manual selection and assigns every service in the system to this staff member.",
    )

    class Meta:
        model = ServiceMaster
        fields = ["master", "services", "assign_all_services"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["master"].queryset = get_staff_queryset(active_only=False).order_by(
            "first_name",
            "last_name",
            "username",
        )
        self.fields["services"].queryset = Service.objects.select_related("category").order_by(
            "category__name",
            "name",
        )
        if self.instance and self.instance.pk and not self.is_bound:
            self.fields["services"].initial = list(
                ServiceMaster.objects.filter(master=self.instance.master).values_list("service_id", flat=True)
            )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("assign_all_services"):
            if not self.fields["services"].queryset.exists():
                raise forms.ValidationError("There are no services to assign yet.")
            return cleaned

        services = cleaned.get("services")
        if not services:
            raise forms.ValidationError("Select at least one service or enable “Assign all current services”.")
        return cleaned

    @transaction.atomic
    def save(self, commit=True):
        instance = super().save(commit=False)
        master = self.cleaned_data["master"]
        if self.cleaned_data.get("assign_all_services"):
            selected_services = list(self.fields["services"].queryset)
        else:
            selected_services = list(self.cleaned_data["services"])

        if not selected_services:
            raise ValidationError("At least one service is required.")

        selected_ids = {service.pk for service in selected_services}
        other_service_ids = set(
            ServiceMaster.objects.filter(master=master)
            .exclude(pk=instance.pk)
            .values_list("service_id", flat=True)
        )

        if instance.pk and instance.master_id == master.pk and instance.service_id in selected_ids:
            anchor_service = next(service for service in selected_services if service.pk == instance.service_id)
        else:
            anchor_service = next(
                (service for service in selected_services if service.pk not in other_service_ids),
                selected_services[0],
            )
            if anchor_service.pk in other_service_ids:
                ServiceMaster.objects.filter(master=master, service=anchor_service).exclude(pk=instance.pk).delete()

        instance.master = master
        instance.service = anchor_service
        instance.save()

        ServiceMaster.objects.filter(master=master).exclude(pk=instance.pk).exclude(
            service_id__in=selected_ids
        ).delete()

        existing_ids = set(ServiceMaster.objects.filter(master=master).values_list("service_id", flat=True))
        for service in selected_services:
            if service.pk not in existing_ids:
                ServiceMaster.objects.create(master=master, service=service)

        return instance


class MasterCreateFullForm(forms.ModelForm):
    # Общие поля
    username = forms.CharField()
    email = forms.EmailField()
    first_name = forms.CharField(required=True)
    last_name = forms.CharField(required=True)
    phone = forms.CharField(required=True)
    birth_date = forms.DateField(required=False, widget=forms.SelectDateWidget(years=range(1950, 2030)))

    password1 = forms.CharField(widget=forms.PasswordInput, required=False)
    password2 = forms.CharField(widget=forms.PasswordInput, required=False)

    class Meta:
        model = MasterProfile
        fields = ['profession', 'bio', 'work_start', 'work_end', 'room', 'photo']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Если редактируем — заменяем пароли на read-only поле
        if self.instance and self.instance.pk:
            user = self.instance.user
            self.fields['password'] = ReadOnlyPasswordHashField(label="Password")
            self.initial['password'] = user.password

            # Удаляем поля пароля
            self.fields.pop('password1')
            self.fields.pop('password2')

            # Заполняем initial для полей пользователя
            self.fields['username'].initial = user.username
            self.fields['email'].initial = user.email
            self.fields['first_name'].initial = user.first_name
            self.fields['last_name'].initial = user.last_name
            # self.fields['room'].initial = user.room

            if hasattr(user, 'userprofile'):
                self.fields['phone'].initial = user.userprofile.phone
                self.fields['birth_date'].initial = user.userprofile.birth_date

    def clean_password2(self):
        # Только если создаём
        if self.instance and self.instance.pk:
            return None

        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")

        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords do not match")

        validate_password(password2)
        return password2

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')

        qs = UserProfile.objects.filter(phone=phone)

        if self.instance.pk:
            # если редактируем, исключаем текущего пользователя
            qs = qs.exclude(user=self.instance.user)

        if qs.exists():
            raise forms.ValidationError("This phone number is already registered!")

        return phone

    def save(self, commit=True):
        if not self.instance.pk:
            # Создание нового пользователя
            user = CustomUserDisplay.objects.create_user(
                username=self.cleaned_data['username'],
                email=self.cleaned_data['email'],
                password=self.cleaned_data['password1'],
                first_name=self.cleaned_data['first_name'],
                last_name=self.cleaned_data['last_name'],
            )
            user.is_staff = True
            user.is_active = True
            user.save()

            # Профиль пользователя
            UserProfile.objects.create(
                user=user,
                phone=self.cleaned_data.get('phone'),

                birth_date=self.cleaned_data.get('birth_date')
            )

            # Назначаем роль Master
            master_role = Role.objects.filter(name="Master").first()
            if master_role:
                user.userrole_set.create(role=master_role)

            # Профиль мастера
            master = super().save(commit=False)
            master.user = user
            if commit:
                master.save()
            return master

        else:
            # Редактирование мастера
            user = self.instance.user
            user.username = self.cleaned_data['username']
            user.email = self.cleaned_data['email']
            user.first_name = self.cleaned_data['first_name']
            user.last_name = self.cleaned_data['last_name']
            user.save()

            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.phone = self.cleaned_data.get('phone')
            profile.birth_date = self.cleaned_data.get('birth_date')
            profile.save()

            return super().save(commit=commit)
        
from django import forms
from core.models import DealerApplication

class DealerApplicationForm(forms.ModelForm):
    class Meta:
        model = DealerApplication
        fields = ["business_name", "website", "phone", "notes"]
        widgets = {
            "business_name": forms.TextInput(attrs={"placeholder": "Business name"}),
            "website": forms.URLInput(attrs={"placeholder": "Website (optional)"}),
            "phone": forms.TextInput(attrs={"placeholder": "Phone"}),
            "notes": forms.Textarea(attrs={"placeholder": "Tell us about your business...", "rows": 4}),
        }

    def clean(self):
        cleaned = super().clean()
        user = self.initial.get("user") or self.current_user
        # Защита: одна заявка на пользователя
        if user and DealerApplication.objects.filter(user=user).exclude(status=DealerApplication.Status.REJECTED).exists():
            raise forms.ValidationError("You already have an application in progress or approved.")
        return cleaned

    # Удобно прокидывать текущего пользователя во время инициализации формы
    def __init__(self, *args, **kwargs):
        self.current_user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        # No tier selection at application time; tiers are revealed post-approval.


class ServiceLeadForm(forms.ModelForm):
    """
    Public-facing form used by landing pages to capture service inquiries.
    """

    class Meta:
        model = ServiceLead
        fields = [
            "full_name",
            "phone",
            "email",
            "vehicle",
            "service_needed",
            "notes",
            "source_page",
            "source_url",
        ]
        widgets = {
            "source_page": forms.HiddenInput(),
            "source_url": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["full_name"].label = "Name"
        self.fields["service_needed"].label = "Service needed"

    def clean_full_name(self):
        name = (self.cleaned_data.get("full_name") or "").strip()
        if not name:
            raise forms.ValidationError("Name is required.")
        return name

    def clean_phone(self):
        raw = (self.cleaned_data.get("phone") or "").strip()
        if not raw:
            raise forms.ValidationError("Phone is required.")
        normalized = re.sub(r"\D", "", raw)
        if raw.startswith("+"):
            normalized = f"+{normalized}"
        try:
            return clean_phone(normalized)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages[0])

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        if not email:
            raise forms.ValidationError("Email is required.")
        return email

    def clean_service_needed(self):
        service = (self.cleaned_data.get("service_needed") or "").strip()
        if not service:
            raise forms.ValidationError("Please choose the service needed.")
        return service

    def clean_vehicle(self):
        return (self.cleaned_data.get("vehicle") or "").strip()

    def clean_notes(self):
        return (self.cleaned_data.get("notes") or "").strip()
