
from django.contrib.admin import SimpleListFilter
from django.contrib import admin

from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (Role, UserRole, Appointment, Service, Payment, PaymentMethod, PaymentStatus,
                     AppointmentStatus, ServiceMaster, AppointmentStatusHistory, PrepaymentOption, AppointmentPrepayment)
from .forms import AppointmentForm, CustomUserChangeForm, CustomUserCreationForm

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
    search_fields = ('username', 'email', 'first_name', 'last_name', 'userprofile__phone')
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
    staff_status.short_description = 'Staff Status'

    def user_roles(self, instance):
        roles = instance.userrole_set.select_related('role').all()
        return ", ".join([ur.role.name for ur in roles]) if roles else "-"
    user_roles.short_description = 'Roles'


# Re-register User with custom admin
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)

class MasterSelector(admin.ModelAdmin):
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



@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    form = AppointmentForm

@admin.register(AppointmentStatusHistory)
class AppointmentStatusHistoryAdmin(admin.ModelAdmin):
    exclude = ('set_by',)  # hide it from form
    list_display = ('appointment', 'status', 'set_by', 'set_at')  # fields to show in table
    def save_model(self, request, obj, form, change):
        if not obj.set_by_id:
            obj.set_by = request.user
        (super().save_model(request, obj, form, change))

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):

    list_display = ('appointment', 'amount', 'method', 'status')  # fields to show in table

@admin.register(AppointmentPrepayment)
class AppointmentPrepaymentAdmin(admin.ModelAdmin):

    list_display = ('appointment', 'option')  # fields to show in table

# Register related models
admin.site.register(Role)
admin.site.register(UserRole)
admin.site.register(Service)
admin.site.register(ServiceMaster, MasterSelector)
admin.site.register(AppointmentStatus)
admin.site.register(PaymentMethod)
admin.site.register(PrepaymentOption)
admin.site.register(PaymentStatus)
