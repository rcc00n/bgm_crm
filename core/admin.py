from django import forms
from django.contrib.admin import SimpleListFilter
from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import UserProfile, Role, UserRole, Appointment, Service, Payment, PaymentMethod, PaymentStatus


class RoleFilter(SimpleListFilter):
    title = 'Role'
    parameter_name = 'role'

    def lookups(self, request, model_admin):
        return [(role.id, role.name) for role in Role.objects.all()]

    def queryset(self, request, queryset):
        if self.value():
            user_ids = UserRole.objects.filter(role_id=self.value()).values_list('user_id', flat=True)
            return queryset.filter(id__in=user_ids)
        return queryset

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
        model = User
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


    # def __init__(self, *args, **kwargs):
    #     super().__init__(*args, **kwargs)
    #     # 💡 Enable native HTML date picker
    #     self.fields['birth_date'].widget = DateInput(attrs={'type': 'date'})



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


# Custom UserAdmin
class CustomUserAdmin(BaseUserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'first_name', 'last_name', 'phone', 'birth_date',
                       'password1', 'password2', 'is_staff', 'is_active', 'is_superuser', 'roles'),
        }),
    )
    list_display = ('username', 'email', 'first_name', 'last_name', 'staff_status', 'phone', 'birth_date', 'user_roles')
    list_filter = ('is_staff', 'is_superuser', 'is_active', RoleFilter)
    fieldsets =(
        (None, {'fields': ('username', 'email', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'phone', 'birth_date')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Roles', {'fields': ('roles',)}),
    )
    def get_fieldsets(self, request, obj=None):
        # Let Django use the default fieldsets
        return super().get_fieldsets(request, obj)

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            return self.add_form
        else:
            return self.form

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if form.cleaned_data.get('roles'):
            UserRole.objects.filter(user=obj).delete()
            for role in form.cleaned_data['roles']:
                UserRole.objects.create(user=obj, role=role)

    def phone(self, instance):
        return instance.userprofile.phone if hasattr(instance, 'userprofile') else '-'

    def birth_date(self, instance):
        return instance.userprofile.birth_date if hasattr(instance, 'userprofile') else '-'

    def staff_status(self, instance):
        return instance.is_staff
    staff_status.boolean = True
    staff_status.short_description = 'Staff'

    def user_roles(self, instance):
        roles = instance.userrole_set.select_related('role').all()
        return ", ".join([ur.role.name for ur in roles]) if roles else "-"
    user_roles.short_description = 'Roles'


# Re-register User with custom admin
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)

class AppointmentAdmin(admin.ModelAdmin):
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "master":
            # Find the Role instance for 'Master'
            master_role = Role.objects.filter(name="Master").first()
            if master_role:
                # Get all User IDs who have the Master role
                master_user_ids = UserRole.objects.filter(role=master_role).values_list('user_id', flat=True)
                kwargs["queryset"] = User.objects.filter(id__in=master_user_ids)
            else:
                kwargs["queryset"] = User.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

# Register related models
admin.site.register(Role)
admin.site.register(UserRole)
admin.site.register(Service)
admin.site.register(Appointment, AppointmentAdmin)
admin.site.register(Payment)
admin.site.register(PaymentMethod)
admin.site.register(PaymentStatus)
