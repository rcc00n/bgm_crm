from dal import autocomplete
from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.core.exceptions import ValidationError
from .models import *

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

    class Meta:
        model = Appointment
        fields = '__all__'
        widgets = {
            'service': autocomplete.ModelSelect2(url='service-autocomplete')
        }
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        instance = self.instance

        # Обнови instance перед вызовом clean()
        instance.master = cleaned_data.get("master")
        instance.start_time = cleaned_data.get("start_time")
        instance.service = cleaned_data.get("service")

        try:
            instance.clean()
        except ValidationError as e:
            raise forms.ValidationError(e)

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.save()

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
    first_name = forms.CharField(required=False)
    last_name = forms.CharField(required=False)
    phone = forms.CharField(required=True)
    birth_date = forms.DateField(required=False, widget=forms.SelectDateWidget(years=range(1950, 2030)))
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False
    )

    class Meta:
        model = User
        fields = [
            'username', 'email', 'first_name', 'last_name',
            'phone', 'birth_date',
            'password1', 'password2',
            'is_staff', 'is_active', 'is_superuser',
            'groups', 'roles'
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
        user.save()

        # Create or update UserProfile
        phone = self.cleaned_data.get('phone')
        birth_date = self.cleaned_data.get('birth_date')
        profile, created = UserProfile.objects.get_or_create(user=user)
        profile.phone = phone
        profile.birth_date = birth_date
        profile.save()

        # Assign roles
        roles = self.cleaned_data.get('roles')

        if roles:
            user.userrole_set.all().delete()
            for role in roles:
                user.userrole_set.create(role=role)

            # Автосоздание MasterProfile
            if any(role.name == "Master" for role in roles):
                MasterProfile.objects.get_or_create(user=user)

        return user

    def clean(self):
        # Optional debug print to inspect cleaned data
        print(self.cleaned_data)

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
        queryset=Role.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False
    )

    files = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'multiple': False}),
        label="Upload files"
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
            'roles',
            'files'
        ]

    def __init__(self, *args, **kwargs):
        """
        Populate form with data from related UserProfile and UserRole
        """
        super().__init__(*args, **kwargs)

        if self.instance and hasattr(self.instance, 'userprofile'):
            self.fields['phone'].initial = self.instance.userprofile.phone
            self.fields['birth_date'].initial = self.instance.userprofile.birth_date

        self.fields['roles'].initial = Role.objects.filter(userrole__user=self.instance)

    def save(self, commit=True):
        """
        Overridden save method to:
        - Save UserProfile data
        - Sync UserRole assignments
        """
        user = super().save(commit=False)
        user.save()

        # Update profile
        phone = self.cleaned_data.get('phone', '')
        birth_date = self.cleaned_data.get('birth_date', None)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.phone = phone
        profile.birth_date = birth_date
        profile.save()

        # Sync roles
        roles = self.cleaned_data.get('roles', [])
        if roles:
            user.userrole_set.all().delete()
            for role in roles:
                user.userrole_set.create(role=role)

            # Автосоздание MasterProfile
            if any(role.name == "Master" for role in roles):
                MasterProfile.objects.get_or_create(user=user)

        uploaded_files = self.files.getlist('files')
        for f in uploaded_files:
            ClientFile.objects.create(
                user=user,
                file=f,
                file_type=f.content_type
            )
        return user

    def clean(self):
        # Optional debug print to inspect cleaned data
        print(self.cleaned_data)



