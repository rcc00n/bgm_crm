from datetime import timedelta, datetime

from django.contrib.admin import SimpleListFilter, DateFieldListFilter
from django.contrib import admin

from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.http import JsonResponse
from django.template.loader import render_to_string

from django.template.response import TemplateResponse
from django.utils.timezone import now, localtime, make_aware
from django.utils.html import escape
from django.utils import timezone
from .models import *
from .forms import AppointmentForm, CustomUserChangeForm, CustomUserCreationForm

# -----------------------------
# Custom filter for filtering users by Role
# -----------------------------
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

# -----------------------------
# Customized User Admin
# -----------------------------
class CustomUserAdmin(BaseUserAdmin):
    """
    Custom admin interface for Django's User model, enhanced with roles and profile fields.
    """
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm

    # Fields shown when adding a new user
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'first_name', 'last_name', 'phone', 'birth_date',
                       'password1', 'password2', 'is_staff', 'is_active', 'is_superuser', 'roles'),
        }),
    )

    # Fields shown in user list
    list_display = ('username', 'email', 'first_name', 'last_name', 'staff_status', 'phone', 'birth_date', 'user_roles')
    list_filter = ('is_staff', 'is_superuser', 'is_active', RoleFilter)
    search_fields = ('username', 'email', 'first_name', 'last_name', 'phone')

    # Field layout when editing a user
    fieldsets = (
        (None, {'fields': ('username', 'email', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'phone', 'birth_date')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Roles', {'fields': ('roles',)}),
    )

    def get_fieldsets(self, request, obj=None):
        # Allow Django to use default fieldsets logic
        return super().get_fieldsets(request, obj)

    def get_form(self, request, obj=None, **kwargs):
        # Return different form on add vs change
        return self.add_form if obj is None else self.form

    def save_model(self, request, obj, form, change):
        # Save user and assign roles
        super().save_model(request, obj, form, change)
        if form.cleaned_data.get('roles'):
            UserRole.objects.filter(user=obj).delete()
            for role in form.cleaned_data['roles']:
                UserRole.objects.create(user=obj, role=role)

    # Custom display methods for user profile fields
    def phone(self, instance):
        return instance.userprofile.phone if hasattr(instance, 'userprofile') else '-'

    def birth_date(self, instance):
        return instance.userprofile.birth_date if hasattr(instance, 'userprofile') else '-'

    @admin.display(boolean=True, description="Staff Status")
    def staff_status(self, instance):
        return instance.is_staff
    staff_status.boolean = True

    @admin.display(description="Roles")
    def user_roles(self, instance):
        roles = instance.userrole_set.select_related('role').all()
        return ", ".join([ur.role.name for ur in roles]) if roles else "-"


# Unregister the default User admin and re-register with our custom one
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


# -----------------------------
# Mixin to filter users who have the "Master" role
# -----------------------------
class MasterSelectorMixing:
    """
    Restricts 'master' foreign key fields to users who have the 'Master' role.
    """
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "master":
            master_role = Role.objects.filter(name="Master").first()
            if master_role:
                master_user_ids = UserRole.objects.filter(role=master_role).values_list('user_id', flat=True)
                kwargs["queryset"] = CustomUserDisplay.objects.filter(id__in=master_user_ids)
            else:
                kwargs["queryset"] = User.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# -----------------------------
# Appointment Admin
# -----------------------------
@admin.register(Appointment)
class AppointmentAdmin(MasterSelectorMixing, admin.ModelAdmin):
    change_list_template = "admin/appointments_calendar.html"
    form = AppointmentForm

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)

        date_str = request.GET.get("date")
        time_str = request.GET.get("time")
        const_master = request.GET.get("master")

        if date_str and time_str:
            try:
                combined = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                initial["start_time"] = make_aware(combined)

            except ValueError:
                pass
        if const_master:
            initial["master"] = const_master

        return initial

    def changelist_view(self, request, extra_context=None):

        today = datetime.today().date()

        selected_date = request.GET.get('date')

        if selected_date:
            selected_date = datetime.strptime(selected_date, '%Y-%m-%d').date()

        else:
            selected_date = timezone.localdate()

        services = Service.objects.all()
        appointment_statuses = AppointmentStatus.objects.all()
        payment_statuses = PaymentStatus.objects.all()

        appointments = Appointment.objects.select_related('client', 'service', 'master')
        masters = CustomUserDisplay.objects.filter(
            id__in=appointments.values_list('master_id', flat=True)
        ).distinct()

        if request.GET.get("service"):
            appointments = appointments.filter(service_id=request.GET["service"])
        if request.GET.get("status"):
            appointments = appointments.filter(appointmentstatushistory__status_id=request.GET["status"])
        if request.GET.get("payment_status"):
            appointments = appointments.filter(payment_status_id__in=request.GET.getlist("payment_status"))

        # Слоты по 15 минут
        start_hour = 8
        end_hour = 21
        slot_times = []
        time_pointer = datetime(2000, 1, 1, start_hour, 0)
        end_time = datetime(2000, 1, 1, end_hour, 0)


        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            action = request.GET.get("action")
            calendar_table = createTable(selected_date, time_pointer, end_time, slot_times, appointments, masters)
            if action == "filter":  # Фильтрация по форме

                html = render_to_string('admin/appointments_calendar_partial.html', {
                    "calendar_table": calendar_table,
                    'masters': masters,
                })
                return JsonResponse({"html": html})

            elif action == "calendar":  # Подгрузка календаря (твоя текущая логика)

                html = render_to_string('admin/appointments_calendar_partial.html', {
                    'calendar_table': calendar_table,
                    'masters': masters,
                }, request=request)

                return JsonResponse({'html': html})

        calendar_table = createTable(selected_date, time_pointer, end_time, slot_times, appointments, masters)
        context = {
            "calendar_table": calendar_table,
            "masters": masters,
            "selected_date": selected_date,
            "prev_date": (selected_date - timedelta(days=1)).strftime("%Y-%m-%d"),
            "next_date": (selected_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "today": today.strftime("%Y-%m-%d"),
            "services": services,
            "appointment_statuses": appointment_statuses,
            "payment_statuses": payment_statuses,
        }

        return TemplateResponse(request, "admin/appointments_calendar.html", context)



# -----------------------------
# Appointment Status History Admin
# -----------------------------
@admin.register(AppointmentStatusHistory)
class AppointmentStatusHistoryAdmin(admin.ModelAdmin):
    """
    Admin interface for tracking status changes of appointments.
    """
    exclude = ('set_by',)
    list_display = ('appointment', 'status', 'set_by', 'set_at')

    def save_model(self, request, obj, form, change):
        if not obj.set_by_id:
            obj.set_by = request.user
        super().save_model(request, obj, form, change)


# -----------------------------
# Payment Admin
# -----------------------------
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """
    Admin interface for payments.
    """
    list_display = ('appointment', 'amount', 'method')
    list_filter = ('method',)
    search_fields = (
        'appointment__client__first_name', 'appointment__client__last_name',
        'appointment__master__first_name', 'appointment__master__last_name',
        'appointment__service__name',
    )


# -----------------------------
# Appointment Prepayment Admin
# -----------------------------
@admin.register(AppointmentPrepayment)
class AppointmentPrepaymentAdmin(admin.ModelAdmin):
    """
    Admin interface for prepayment options tied to appointments.
    """
    list_display = ('appointment', 'option')


# -----------------------------
# Hidden Proxy Admin for CustomUserDisplay
# -----------------------------
@admin.register(CustomUserDisplay)
class CustomUserDisplayAdmin(admin.ModelAdmin):
    """
    Admin registration for proxy model CustomUserDisplay (hidden from UI).
    """
    def get_model_perms(self, request):
        # Hide from admin index
        return {}


# -----------------------------
# Service Master Admin
# -----------------------------
@admin.register(ServiceMaster)
class ServiceMasterAdmin(MasterSelectorMixing, admin.ModelAdmin):
    """
    Admin interface to assign masters to services.
    """
    list_display = ('master', 'service')
    search_fields = ('master__first_name', 'master__last_name', 'service__name')


# -----------------------------
# Service Admin
# -----------------------------
@admin.register(Service)
class ServiceAdmin(MasterSelectorMixing, admin.ModelAdmin):
    """
    Admin interface for services.
    """
    list_display = ('name', 'base_price', 'duration_min')
    search_fields = ('name',)


# -----------------------------
# Notification Admin
# -----------------------------
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """
    Admin interface for notifications (email/SMS).
    """
    list_display = ('user', 'appointment', 'channel', 'short_message')
    list_filter = (('sent_at', DateFieldListFilter), 'channel')
    search_fields = ('user__first_name', 'user__last_name', 'appointment__service__name')
    ordering = ['-sent_at']

    @admin.display(description="message")
    def short_message(self, obj):
        """
        Truncates long messages to first 10 words.
        """
        words = obj.message.split()
        return ' '.join(words[:10]) + ('...' if len(words) > 10 else '')


# -----------------------------
# Client File Admin
# -----------------------------
@admin.register(ClientFile)
class ClientFileAdmin(admin.ModelAdmin):
    """
    Admin interface for managing user-uploaded files.
    """
    list_display = ('user', 'file_type', 'file')
    fields = ('user', 'file', 'file_type')
    list_filter = (('uploaded_at', DateFieldListFilter), 'file_type')
    search_fields = ('user__first_name', 'user__last_name')
    ordering = ['-uploaded_at']


# -----------------------------
# Register remaining models directly
# -----------------------------
admin.site.register(Role)
admin.site.register(UserRole)
admin.site.register(AppointmentStatus)
admin.site.register(PaymentMethod)
admin.site.register(PrepaymentOption)
admin.site.register(PaymentStatus)

def createTable(selected_date, time_pointer, end_time, slot_times, appointments, masters):
    while time_pointer <= end_time:
        slot_times.append(time_pointer.strftime('%H:%M'))
        time_pointer += timedelta(minutes=15)

        # Мапа: master_id + time → appointment (только начало)
    slot_map = {}  # slot_map[master_id][time_str] = {...}
    skip_map = {}  # skip_map[master_id][time_str] = True

    for appt in appointments:
        local_start = localtime(appt.start_time)
        if local_start.date() != selected_date:
            continue

        master_id = appt.master_id
        time_key = local_start.strftime('%H:%M')
        duration = appt.service.duration_min
        rowspan = max(1, duration // 15)

        if master_id not in slot_map:
            slot_map[master_id] = {}
            skip_map[master_id] = {}

        slot_map[master_id][time_key] = {
            "appointment": appt,
            "rowspan": rowspan,
        }

        # Отметим следующие ячейки как "пропущенные"
        for i in range(1, rowspan):
            t = local_start + timedelta(minutes=i * 15)
            skip_map[master_id][t.strftime('%H:%M')] = True

    # Генерируем таблицу
    calendar_table = []
    for time_str in slot_times:
        row = {"time": time_str, "cells": []}
        for master in masters:
            master_id = master.id
            if master_id in skip_map and time_str in skip_map[master_id]:
                row["cells"].append({"skip": True})
            elif master_id in slot_map and time_str in slot_map[master_id]:
                appt = slot_map[master_id][time_str]["appointment"]
                rowspan = slot_map[master_id][time_str]["rowspan"]
                last_status = appt.appointmentstatushistory_set.order_by('-set_at').first()
                status_name = last_status.status.name if last_status else "Unknown"
                local_start = localtime(appt.start_time)
                local_end = local_start + timedelta(minutes=appt.service.duration_min)
                html = f"""
                        <div>
                            <div style="font-size:16px;">
                                {escape(local_start.strftime('%I:%M').lstrip('0'))} – {escape(local_end.strftime('%I:%M').lstrip('0'))}
                                <strong>{escape(appt.client.get_full_name())}</strong>
                            </div>
                            <div style="font-size:16px;">
                                {escape(appt.service.name)}
                            </div>
                        </div>
                    """
                row["cells"].append({
                    "html": html,
                    "rowspan": rowspan,
                    "appt_id": appt.id,
                    "appointment": appt,
                    "client": escape(appt.client.get_full_name()),
                    "phone": escape("+1 " + getattr(appt.client.userprofile, "phone", "")),
                    "service": escape(appt.service.name),
                    "status": status_name,
                    "master": escape(master.get_full_name()),
                    "time_label": f"{local_start.strftime('%I:%M%p').lstrip('0')} - {local_end.strftime('%I:%M%p').lstrip('0')}",
                    "duration": f"{appt.service.duration_min}min",
                    "price": f"${appt.service.base_price}",
                })

            else:
                row["cells"].append({
                    "html": '',
                    "rowspan": 1,
                    "master_id": master_id,
                })
        calendar_table.append(row)
    return calendar_table