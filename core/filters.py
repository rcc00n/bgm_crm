from django.contrib.admin import SimpleListFilter

from .utils import get_staff_queryset
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
    title = 'Staff'
    parameter_name = 'staff'

    def lookups(self, request, model_admin):
        masters = get_staff_queryset(active_only=False).order_by("first_name", "last_name", "username")
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
            staff_ids = get_staff_queryset(active_only=False).values_list("id", flat=True)
            return queryset.filter(id__in=staff_ids)
        return queryset
