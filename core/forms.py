from dal import autocomplete
from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import Appointment, Role, User, UserProfile, CustomUserDisplay

class AppointmentForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = '__all__'
        widgets = {
            'master_service': autocomplete.ModelSelect2(url='service-master-autocomplete')
        }


# Custom user creation form with roles
class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(required=False)
    last_name = forms.CharField(required=False)
    phone = forms.CharField(required=False)
    birth_date = forms.DateField(required=False, widget=forms.SelectDateWidget(years=range(1950, 2030)))
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False
    )

    class Meta:
        model = CustomUserDisplay
        fields = [
            'username', 'email', 'first_name', 'last_name',
            'phone', 'birth_date',
            'password1', 'password2',
            'is_staff', 'is_active', 'is_superuser',
            'groups', 'roles'
        ]
    def save(self, commit=True):

        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])

        user.save()

        # Save profile data
        phone = self.cleaned_data.get('phone')
        birth_date = self.cleaned_data.get('birth_date')
        profile, created = UserProfile.objects.get_or_create(user=user)

        profile.phone = phone
        profile.birth_date = birth_date
        profile.save()

        # Save roles
        roles = self.cleaned_data.get('roles')
        print("CUSTOM SAVE METHOD CALLED")
        if roles:
            user.userrole_set.all().delete()
            for role in roles:
                user.userrole_set.create(role=role)

        return user

    def clean(self):
        print(self.cleaned_data)


class CustomUserChangeForm(UserChangeForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(required=False)
    last_name = forms.CharField(required=False)
    phone = forms.CharField(required=False)
    birth_date = forms.DateField(required=False)
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False
    )

    class Meta:
        model = CustomUserDisplay
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
            'roles'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Load data from UserProfile if exists
        if self.instance and hasattr(self.instance, 'userprofile'):
            self.fields['phone'].initial = self.instance.userprofile.phone
            self.fields['birth_date'].initial = self.instance.userprofile.birth_date
            self.fields['roles'].initial = Role.objects.filter(userrole__user=self.instance)

        # self.fields['birth_date'].widget = DateInput(attrs={'type': 'date'})

    def save(self, commit=True):
        user = super().save(commit=False)

        # Save user first to ensure it has a primary key

        user.save()

        # Save or update profile
        phone = self.cleaned_data.get('phone', '')
        birth_date = self.cleaned_data.get('birth_date', None)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.phone = phone
        profile.birth_date = birth_date
        profile.save()

        # Sync roles
        user.userrole_set.all().delete()
        roles = self.cleaned_data.get('roles', [])
        for role in roles:
            user.userrole_set.create(role=role)

        return user


    def clean(self):
        cleaned_data = self.cleaned_data
        print(cleaned_data)
