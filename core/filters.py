from django.contrib.admin import SimpleListFilter
from .models import *

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

class MasterOnlyFilter(SimpleListFilter):
    title = 'Master'
    parameter_name = 'master'

    def lookups(self, request, model_admin):
        master_role = Role.objects.filter(name="Master").first()
        if not master_role:
            return []
        master_ids = UserRole.objects.filter(role=master_role).values_list('user_id', flat=True)
        masters = CustomUserDisplay.objects.filter(id__in=master_ids)
        return [(m.id, m.get_full_name() or m.username) for m in masters]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(master_id=self.value())
        return queryset

class MasterRoleFilter(SimpleListFilter):
    title = "Is Master"
    parameter_name = "is_master"

    def lookups(self, request, model_admin):
        return (("yes", "Yes"),)

    def queryset(self, request, queryset):
        if self.value() == "yes":
            master_role = Role.objects.filter(name="Master").first()
            if master_role:
                master_ids = UserRole.objects.filter(role=master_role).values_list("user_id", flat=True)
                return queryset.filter(id__in=master_ids)
        return queryset