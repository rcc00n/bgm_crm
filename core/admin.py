from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import UserProfile, Role, Appointment, Service, Payment

# Inline model for UserProfile
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'User Profile'
    fk_name = 'user'

# Extend UserAdmin
class CustomUserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'staff_status', 'phone', 'birth_date')

    def phone(self, instance):
        return instance.userprofile.phone if hasattr(instance, 'userprofile') else '-'

    def birth_date(self, instance):
        return instance.userprofile.birth_date if hasattr(instance, 'userprofile') else '-'

    def staff_status(self, instance):
        return instance.is_staff

    staff_status.boolean = True
    staff_status.short_description = 'Staff Status'

# Re-register with updated config
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)



admin.site.register(Role)
admin.site.register(Service)
admin.site.register(Appointment)
admin.site.register(Payment)