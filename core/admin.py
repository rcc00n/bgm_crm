from bisect import bisect_left
from calendar import monthrange
from decimal import Decimal

from django.contrib.admin import DateFieldListFilter

from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.contrib import admin, messages
from django import forms
from django.db import models
from django.db.models import Sum, Count
from itertools import cycle
from django.utils.timezone import localtime, datetime, make_aware, localdate
from django.utils import timezone
from django.utils.html import escape
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.template.defaultfilters import filesizeformat
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.admin import GenericStackedInline
from django.http import JsonResponse
from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import json
import csv
from django.urls import path, reverse, NoReverseMatch
from django.http import HttpResponse, HttpResponseRedirect
from ckeditor_uploader.widgets import CKEditorUploadingWidget
from .filters import *
from .models import *
from .forms import *
from core.email_templates import (
    email_accent_color,
    email_bg_color,
    email_brand_name,
    email_brand_tagline,
    email_company_address,
    email_company_phone,
    email_company_website,
    email_dark_color,
    template_tokens,
)
from core.services.analytics import summarize_web_analytics, summarize_web_analytics_periods
from core.services.email_campaigns import (
    estimate_campaign_audience,
    import_email_subscribers,
    render_campaign_email,
    send_campaign,
)
from core.services.pagecopy_preview import (
    PREVIEW_CONFIG,
    PreviewCopy,
    render_pagecopy_preview,
)
from core.utils import get_staff_queryset, format_currency
from datetime import timedelta, time
# -----------------------------
# Custom filter for filtering users by Role
# -----------------------------

# Переопределение index view
# ── REPLACE this function in core/admin.py ─────────────────────────────────────
def custom_index(request):
    from datetime import timedelta  # (на случай, если не импортирован наверху)
    from django.utils import timezone
    today = timezone.localdate()

    # windows for aggregates
    week_ago = today - timedelta(days=6)
    last_14 = today - timedelta(days=13)
    last_30 = today - timedelta(days=29)
    last_60 = today - timedelta(days=59)

    # base querysets
    appointments_qs = Appointment.objects.filter(start_time__date__range=[week_ago, today])
    payments_qs = Payment.objects.filter(appointment__start_time__date__range=[week_ago, today])

    is_master = request.user.userrole_set.filter(
        role__name="Master", user__is_superuser=False
    ).exists()

    # 7-day sales line (как раньше)
    chart_data, total_sales = [], 0.0
    for i in range(7):
        day = today - timedelta(days=6 - i)
        sales = payments_qs.filter(appointment__start_time__date=day)\
                           .aggregate(total=Sum("amount"))["total"] or 0
        appts = appointments_qs.filter(start_time__date=day).count()
        total_sales += float(sales)
        chart_data.append({"day": day.strftime("%a %d"), "sales": float(sales), "appointments": appts})

    # statuses / counters
    confirmed = AppointmentStatus.objects.filter(name="Confirmed").first()
    cancelled = AppointmentStatus.objects.filter(name="Cancelled").first()

    upcoming = Appointment.objects.filter(
        start_time__date__gte=today, start_time__date__lte=today + timedelta(days=7)
    )
    confirmed_count = upcoming.filter(appointmentstatushistory__status=confirmed).count()
    cancelled_count = upcoming.filter(appointmentstatushistory__status=cancelled).count()

    # tables
    top_services = Service.objects.annotate(count=Count("appointment")).order_by("-count")[:5]

    first_day = today.replace(day=1)
    masters = get_staff_queryset(active_only=False).annotate(
        total=Sum(
            "appointments_as_master__service__base_price",
            filter=models.Q(appointments_as_master__start_time__date__gte=first_day),
        )
    )
    top_masters = sorted(masters, key=lambda m: m.total or 0, reverse=True)[:3]

    recent_appointments = Appointment.objects.select_related("client", "master", "service")\
                                             .order_by("-start_time")[:20]
    today_appointments = Appointment.objects.filter(
        start_time__date=today, start_time__gte=timezone.now()
    )
    if is_master:
        today_appointments = today_appointments.filter(master=request.user)
    today_appointments = today_appointments.order_by("start_time")

    # daily confirmed/cancelled for upcoming chart (последние 7 дней)
    week = [today - timedelta(days=6 - i) for i in range(7)]
    daily_counts = []
    for day in week:
        daily_counts.append({
            "day": day.strftime("%a %d"),
            "confirmed": Appointment.objects.filter(
                start_time__date=day, appointmentstatushistory__status=confirmed
            ).count(),
            "cancelled": Appointment.objects.filter(
                start_time__date=day, appointmentstatushistory__status=cancelled
            ).count(),
        })

    # ── NEW: five datasets for 5 new charts ────────────────────────────────────
    # 1) Revenue by Service (без models.F и с явным маппингом)
    _raw_service_rev = (
        Payment.objects.filter(appointment__start_time__date__gte=last_30)
        .values("appointment__service__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")[:8]
    )
    revenue_by_service = [
        {"name": r["appointment__service__name"] or "—", "total": float(r["total"] or 0)}
        for r in _raw_service_rev
    ]


    # 2) Revenue by Team Member (last 30d)
    raw_master_rev = (
        Payment.objects.filter(appointment__start_time__date__gte=last_30)
        .values("appointment__master__first_name", "appointment__master__last_name")
        .annotate(total=Sum("amount"))
        .order_by("-total")[:8]
    )
    master_revenue = [
        {
            "name": (r["appointment__master__first_name"] or "") + " " + (r["appointment__master__last_name"] or ""),
            "total": float(r["total"] or 0),
        }
        for r in raw_master_rev
    ]

    # 3) Appointments by Weekday (last 60d)
    weekday_counts = [{"day": d, "count": 0} for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]]
    for dt in Appointment.objects.filter(start_time__date__gte=last_60)\
                                 .values_list("start_time", flat=True):
        wd = timezone.localtime(dt).weekday()  # Mon=0..Sun=6
        weekday_counts[wd]["count"] += 1

    # 4) Payment Methods breakdown (исключаем конфликт имени)
    _raw_methods = (
        Payment.objects.filter(appointment__start_time__date__gte=last_30)
        .values("method__name")                # группируем по названию метода
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    payment_methods = [
        {"method": r["method__name"] or "—", "count": r["count"]}
        for r in _raw_methods
    ]

    # 5) Status trend (last 14d)
    status_days = [today - timedelta(days=i) for i in range(13, -1, -1)]
    status_trend = []
    for day in status_days:
        status_trend.append({
            "day": day.strftime("%b %d"),
            "confirmed": Appointment.objects.filter(
                start_time__date=day, appointmentstatushistory__status=confirmed
            ).count(),
            "cancelled": Appointment.objects.filter(
                start_time__date=day, appointmentstatushistory__status=cancelled
            ).count(),
        })

    analytics_summary = summarize_web_analytics(window_days=7) if not is_master else None
    analytics_periods = (
        summarize_web_analytics_periods(
            windows=[1, 7, 30],
            cache={7: analytics_summary} if analytics_summary else None,
        )
        if not is_master
        else None
    )

    latest_ui_check = ClientUiCheckRun.objects.order_by("-started_at").first()
    ui_check_next_due = None
    ui_check_due = False
    ui_check_running = False
    if latest_ui_check:
        ui_check_next_due = latest_ui_check.started_at + timedelta(days=3)
        ui_check_due = ui_check_next_due <= timezone.now()
        ui_check_running = (
            latest_ui_check.status == ClientUiCheckRun.Status.RUNNING
            and latest_ui_check.started_at >= timezone.now() - timedelta(hours=6)
        )

    context = admin.site.each_context(request)
    context.update({
        "is_master": is_master,
        "daily_appointments": daily_counts,
        "chart_data": chart_data,
        "total_sales": total_sales,
        "upcoming_total": upcoming.count(),
        "confirmed_count": confirmed_count,
        "cancelled_count": cancelled_count,
        "top_services": top_services,
        "top_masters": top_masters,
        "today": localdate(),
        "recent_appointments": recent_appointments,
        "today_appointments": today_appointments,
        # NEW datasets for charts:
        "service_revenue": revenue_by_service,
        "master_revenue": master_revenue,
        "weekday_counts": weekday_counts,
        "payment_methods": payment_methods,
        "status_trend": status_trend,
        "web_analytics": analytics_summary,
        "web_analytics_periods": analytics_periods,
        "latest_ui_check": latest_ui_check,
        "ui_check_next_due": ui_check_next_due,
        "ui_check_due": ui_check_due,
        "ui_check_running": ui_check_running,
    })
    return TemplateResponse(request, "admin/index.html", context)
# ───────────────────────────────────────────────────────────────────────────────

# Переопределить главную страницу
admin.site.index = custom_index
class ExportCsvMixin:
    export_fields = None  # список полей; можно переопределить в admin

    def get_urls(self):
        opts = self.model._meta
        return [
            path(
                "export-csv/",
                self.admin_site.admin_view(self.export_all_csv),
                name=f"{opts.app_label}_{opts.model_name}_export_csv"
            )
        ] + super().get_urls()

    def export_all_csv(self, request):
        queryset = self.get_queryset(request)

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename={self.model._meta.model_name}.csv'

        fields = self.export_fields or [field.name for field in self.model._meta.fields]
        writer = csv.writer(response)
        writer.writerow(fields)

        for obj in queryset:
            if hasattr(self, 'get_export_row'):
                row = self.get_export_row(obj)
            else:
                row = [getattr(obj, field) for field in fields]
            writer.writerow(row)

        return response

    def changelist_view(self, request, extra_context=None):
        # Попробуем reverse без краша
        extra_context = extra_context or {}
        try:
            opts = self.model._meta
            export_url = reverse(f'admin:{opts.app_label}_{opts.model_name}_export_csv')
            export_url += f"?{request.GET.urlencode()}"
            extra_context['export_url'] = export_url
        except NoReverseMatch:
            extra_context['export_url'] = None

        return super().changelist_view(request, extra_context=extra_context)
# -----------------------------
# Customized User Admin
# -----------------------------
class CustomUserAdmin(ExportCsvMixin ,BaseUserAdmin):
    """
    Custom admin interface for Django's User model, enhanced with roles and profile fields.
    """
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    export_fields = ['username', 'email', 'first_name', 'last_name', 'phone', 'birth_date', 'user_roles','is_staff', 'is_superuser', 'is_active']

    def get_export_row(self, obj):
        phone = obj.userprofile.phone if hasattr(obj, 'userprofile') else ''
        birth_date = obj.userprofile.birth_date if hasattr(obj, 'userprofile') else ''
        roles = ", ".join([ur.role.name for ur in obj.userrole_set.all()])

        return [
            obj.username,
            obj.email,
            obj.first_name,
            obj.last_name,
            phone,
            birth_date,
            roles,
            obj.is_staff,
            obj.is_superuser,
            obj.is_active,
        ]
    # Fields shown when adding a new user
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'first_name', 'last_name', 'phone', 'birth_date',
                       'password1', 'password2', 'is_staff', 'is_active', 'is_superuser'),
        }),
    )

    # Fields shown in user list
    list_display = ('username', 'email', 'first_name', 'last_name', 'staff_status', 'phone', 'birth_date', 'user_roles', 'send_notify_button')
    list_filter = ('is_staff', 'is_superuser', 'is_active', RoleFilter)
    search_fields = ('username', 'email', 'first_name', 'last_name', 'userprofile__phone')

    # Field layout when editing a user
    fieldsets = (
        (None, {'fields': ('username', 'email', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'phone', 'birth_date')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Admin Notifications', {'fields': ('admin_notification_sections',)}),
        ('Files', {'fields': ('files', 'files_overview')}),
    )
    readonly_fields = BaseUserAdmin.readonly_fields + ('files_overview',)

    def get_fieldsets(self, request, obj=None):
        # Allow Django to use default fieldsets logic
        return super().get_fieldsets(request, obj)

    def get_form(self, request, obj=None, **kwargs):
        # Return different form on add vs change
        return self.add_form if obj is None else self.form

    def save_model(self, request, obj, form, change):
        # Save user and assign roles
        super().save_model(request, obj, form, change)

    @admin.display(description="Existing files")
    def files_overview(self, obj):
        if not obj or not obj.pk:
            return "Files will appear after the user is saved."
        files_qs = obj.clientfile_set.order_by('-uploaded_at')
        if not files_qs.exists():
            return "No files yet."
        rows = format_html_join(
            "",
            "<li style='margin-bottom:.4rem'>"
            "<a href=\"{0}\" target=\"_blank\" rel=\"noopener\" style='font-weight:600'>{1}</a>"
            "<div style='font-size:.85rem;color:#999'>"
            "{2} • {3} • {4}"
            "</div>"
            "</li>",
            (
                (
                    f.file.url,
                    f.filename or f.file.name,
                    filesizeformat(f.file_size) if f.file_size else "—",
                    f.get_uploaded_by_display(),
                    timezone.localtime(f.uploaded_at).strftime("%b %d, %Y %H:%M") if f.uploaded_at else "—",
                )
                for f in files_qs[:8]
            )
        )
        extra = ""
        remaining = files_qs.count() - 8
        if remaining > 0:
            extra = format_html("<div style='margin-top:.5rem;color:#999'>+ {} more file(s)</div>", remaining)
        return format_html("<ul style='margin:0;padding-left:1rem;list-style:disc'>{}</ul>{}", rows, extra)

    # Custom display methods for user profile fields
    def phone(self, instance):
        return instance.userprofile.phone if hasattr(instance, 'userprofile') else '-'

    def birth_date(self, instance):
        return instance.userprofile.birth_date if hasattr(instance, 'userprofile') else '-'

    @admin.display(description="")
    def send_notify_button(self, obj):
        return mark_safe(
            f'<button type="button" class="send-notify-btn" '
            f'data-user-id="{obj.id}" '
            f'data-user-name="{obj.get_full_name() or obj.username}">Send Notification</button>'
        )
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('send_notification/', self.admin_site.admin_view(self.send_notification_view), name='send_notification'),
        ]
        return custom_urls + urls

    @method_decorator(csrf_exempt)
    def send_notification_view(self, request):
        if request.method == "POST":
            data = json.loads(request.body)
            user_id = data.get("user_id")
            message = data.get("message")

            user = CustomUserDisplay.objects.filter(id=user_id).first()
            if user:
                Notification.objects.create(
                    user=user,
                    message=message,
                    channel="email"  # или sms
                )
                return JsonResponse({"status": "ok"})

        return JsonResponse({"status": "error"}, status=400)
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
        if db_field.name == "master" and "queryset" not in kwargs:
            kwargs["queryset"] = get_staff_queryset()
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "master" and field:
            field.label = STAFF_DISPLAY_NAME
        return field



@admin.register(MasterAvailability)
class MasterAvailabilityAdmin(ExportCsvMixin, MasterSelectorMixing, admin.ModelAdmin):
    list_display = ('id', 'master', 'start_time', 'end_time')
    list_filter  = ('master',)
    search_fields = ("master__first_name", "master__last_name", "reason")
    export_fields = ["master", "start_time", "end_time", "reason"]

    def has_add_permission(self, request):
        return request.user.has_perm("core.add_masteravailability")

    def has_change_permission(self, request, obj=None):
        if not request.user.has_perm("core.change_masteravailability"):
            return False
        if obj is None or not hasattr(request.user, "master_profile") or request.user.is_superuser:
            return True
        return obj.master_id == request.user.id

    def has_delete_permission(self, request, obj=None):
        if not request.user.has_perm("core.delete_masteravailability"):
            return False
        if obj is None or not hasattr(request.user, "master_profile") or request.user.is_superuser:
            return True
        return obj.master_id == request.user.id

    # --- только свои time off ---
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if hasattr(request.user, "master_profile") and not request.user.is_superuser:
            return qs.filter(master=request.user)
        return qs

    # --- мастер фиксируется для мастера ---
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "master" and hasattr(request.user, "master_profile") and not request.user.is_superuser:
            kwargs["queryset"] = CustomUserDisplay.objects.filter(id=request.user.id)
            kwargs["initial"] = request.user.id
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

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

    @admin.display(description=STAFF_DISPLAY_NAME, ordering="master__first_name")
    def staff(self, obj):
        full_name = obj.master.get_full_name()
        return full_name if full_name else obj.master.username


# -----------------------------
# Appointment Admin
# -----------------------------
@admin.register(Appointment)
class AppointmentAdmin(MasterSelectorMixing, admin.ModelAdmin):
    change_list_template = "admin/appointments_calendar.html"
    form = AppointmentForm
    fields = [
        'client',
        'contact_name',
        'contact_email',
        'contact_phone',
        'master',
        'service',
        'start_time',
        'payment_status',
        'status',
    ]
    class Media:
        js = ("admin/js/appointment_contact_autofill.js",)
    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)

        date_str = request.GET.get("date")
        time_str = request.GET.get("time")
        const_master = request.GET.get("master")

        if hasattr(request.user, "master_profile") and not request.user.is_superuser:
            initial["master"] = request.user.id

        if date_str and time_str:
            try:
                combined = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                initial["start_time"] = make_aware(combined)

            except ValueError:
                pass
        if const_master:
            initial["master"] = const_master


        return initial

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)

        class WrappedForm(form):
            def __new__(cls, *args, **kwargs_inner):
                form.base_fields['status'] = forms.ModelChoiceField(queryset=AppointmentStatus.objects.all(), required=False, label='Appointment status')
                if obj:
                    last_status = obj.appointmentstatushistory_set.order_by('-set_at').first()
                    if last_status:
                        form.base_fields['status'].initial = last_status.status
                kwargs_inner['user'] = request.user
                return form(*args, **kwargs_inner)

        return WrappedForm

    # --- права ---
    def has_add_permission(self, request):
        return request.user.has_perm("core.add_appointment")

    def has_change_permission(self, request, obj=None):
        if not request.user.has_perm("core.change_appointment"):
            return False
        if obj is None or not hasattr(request.user, "master_profile") or request.user.is_superuser:
            return True
        return obj.master_id == request.user.id

    def has_delete_permission(self, request, obj=None):
        if not request.user.has_perm("core.delete_appointment"):
            return False
        if obj is None or not hasattr(request.user, "master_profile") or request.user.is_superuser:
            return True
        return obj.master_id == request.user.id

    # --- только свои записи мастеру ---
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if hasattr(request.user, "master_profile") and not request.user.is_superuser:
            return qs.filter(master=request.user)
        return qs

    # --- поле master фиксируем для мастера ---
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "master" and hasattr(request.user, "master_profile") and not request.user.is_superuser:
            kwargs["queryset"] = CustomUserDisplay.objects.filter(id=request.user.id)
            kwargs["initial"] = request.user.id
        return super().formfield_for_foreignkey(db_field, request, **kwargs)




    def changelist_view(self, request, extra_context=None):

        selected_date = request.GET.get('date')

        if selected_date:
            selected_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        else:
            selected_date = timezone.localdate()

        calendar_view = request.GET.get("view", "week")
        if calendar_view not in {"day", "week", "month"}:
            calendar_view = "week"

        services = Service.objects.all()
        appointment_statuses = AppointmentStatus.objects.all()
        payment_statuses = PaymentStatus.objects.all()

        appointments = (
            Appointment.objects.select_related('client', 'service', 'master')
            .prefetch_related(
                'appointmentstatushistory_set__status',
                'appointmentpromocode__promocode',
            )
        )
        cancelled_status = AppointmentStatus.objects.filter(name="Cancelled").first()
        if not request.GET.get("status"):
            appointments = appointments.exclude(
                appointmentstatushistory__status=cancelled_status
            )
        else:
            # Если выбран какой-либо статус
            selected_status = request.GET.get("status")
            if str(cancelled_status.id) != selected_status:
                appointments = appointments.exclude(
                    appointmentstatushistory__status=cancelled_status
                )
        if hasattr(request.user, "master_profile") and not request.user.is_superuser:
            masters_qs = CustomUserDisplay.objects.filter(id=request.user.id)
        else:
            masters_qs = get_staff_queryset(active_only=True)
        masters = list(masters_qs.select_related("master_profile"))
        if calendar_view == "week":
            range_start_date = selected_date - timedelta(days=selected_date.weekday())
            range_end_date = range_start_date + timedelta(days=6)
        elif calendar_view == "month":
            month_start = selected_date.replace(day=1)
            month_last = selected_date.replace(day=monthrange(selected_date.year, selected_date.month)[1])
            range_start_date = month_start - timedelta(days=month_start.weekday())
            range_end_date = month_last + timedelta(days=(6 - month_last.weekday()))
        else:
            range_start_date = selected_date
            range_end_date = selected_date

        range_start = make_aware(datetime.combine(range_start_date, datetime.min.time()))
        range_end = make_aware(datetime.combine(range_end_date, datetime.max.time()))

        availabilities = MasterAvailability.objects.filter(
            start_time__lte=range_end,
            end_time__gte=range_start
        )
        appointments = appointments.filter(start_time__gte=range_start, start_time__lte=range_end)
        if request.GET.get("service"):
            appointments = appointments.filter(service_id=request.GET["service"])
        if request.GET.get("status"):
            appointments = appointments.filter(appointmentstatushistory__status_id=request.GET["status"])
        if request.GET.get("payment_status"):
            appointments = appointments.filter(payment_status_id__in=request.GET.getlist("payment_status"))

        appointments_for_range = list(appointments)
        availabilities_for_range = list(availabilities)

        calendar_table = []
        week_table = []
        week_dates = []
        month_grid = []
        month_day_names = []

        if calendar_view == "day":
            slot_times = []
            grid_start, grid_end = determine_calendar_window(masters, appointments_for_range)
            calendar_table = createTable(selected_date, grid_start, grid_end, slot_times, appointments_for_range, masters, availabilities_for_range)
        elif calendar_view == "week":
            grid_start, grid_end = determine_calendar_window(masters, appointments_for_range)
            slot_times = build_slot_times(grid_start, grid_end)
            week_dates = [range_start_date + timedelta(days=i) for i in range(7)]
            week_table = build_week_table(week_dates, slot_times, appointments_for_range, masters)
        else:
            month_day_names = [datetime(2020, 1, 6) + timedelta(days=i) for i in range(7)]
            month_grid = build_month_grid(range_start_date, range_end_date, selected_date.month, appointments_for_range, masters)

        calendar_context = {
            "calendar_view": calendar_view,
            "masters": masters,
            "calendar_table": calendar_table,
            "week_dates": week_dates,
            "week_table": week_table,
            "month_grid": month_grid,
            "month_day_names": month_day_names,
        }


        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            action = request.GET.get("action")

            if action == "filter":  # Фильтрация по форме

                html = render_to_string('admin/appointments_calendar_partial.html', calendar_context)
                return JsonResponse({"html": html})

            elif action == "calendar":  # Подгрузка календаря (твоя текущая логика)

                html = render_to_string('admin/appointments_calendar_partial.html', calendar_context, request=request)

                return JsonResponse({'html': html})

        response = super().changelist_view(request, extra_context=extra_context)

        if hasattr(response, "context_data"):
            context = response.context_data
            context.update({
                "calendar_view": calendar_view,
                "calendar_table": calendar_table,
                "week_dates": week_dates,
                "week_table": week_table,
                "month_grid": month_grid,
                "month_day_names": month_day_names,
                "masters": masters,
                "selected_date": selected_date,
                "prev_date": (selected_date - timedelta(days=1)).strftime("%Y-%m-%d"),
                "next_date": (selected_date + timedelta(days=1)).strftime("%Y-%m-%d"),
                "today": timezone.localdate().strftime("%Y-%m-%d"),
                "services": services,
                "appointment_statuses": appointment_statuses,
                "payment_statuses": payment_statuses,
            })

        return response

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "move/",
                self.admin_site.admin_view(self.move_appointment_view),
                name="core_appointment_move",
            ),
            path(
                "quick_add/",
                self.admin_site.admin_view(self.quick_add_view),
                name="core_appointment_quick_add",
            ),
        ]
        return custom_urls + urls

    def quick_add_view(self, request):
        """
        Lightweight endpoint used by the calendar "quick add" modal.
        Creates an Appointment using the same validation rules as the admin form.
        """
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": "POST required."}, status=405)

        if not self.has_add_permission(request):
            return JsonResponse({"ok": False, "error": "Permission denied."}, status=403)

        date_str = (request.POST.get("date") or "").strip()
        time_str = (request.POST.get("time") or "").strip()

        if not date_str or not time_str:
            return JsonResponse({"ok": False, "error": "Missing date/time."}, status=400)

        try:
            combined = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            return JsonResponse({"ok": False, "error": "Invalid date/time format."}, status=400)

        post = request.POST.copy()
        post["start_time"] = combined.strftime("%Y-%m-%d %H:%M")

        # Masters can only create appointments for themselves.
        if hasattr(request.user, "master_profile") and not request.user.is_superuser:
            post["master"] = str(request.user.id)

        form = AppointmentForm(data=post, user=request.user)
        if not form.is_valid():
            errors = {k: [str(m) for m in v] for k, v in form.errors.items()}
            return JsonResponse({"ok": False, "errors": errors}, status=400)

        appt = form.save()
        return JsonResponse({"ok": True, "appointment_id": str(appt.pk)})

    def move_appointment_view(self, request):
        if request.method != "POST":
            return JsonResponse({"ok": False, "error": "POST required."}, status=405)

        appointment_id = request.POST.get("appointment_id")
        date_str = request.POST.get("date")
        time_str = request.POST.get("time")
        master_id = (request.POST.get("master_id") or "").strip() or None

        if not appointment_id or not date_str or not time_str:
            return JsonResponse({"ok": False, "error": "Missing appointment_id/date/time."}, status=400)

        try:
            appt = Appointment.objects.select_related("service", "master").get(pk=appointment_id)
        except (Appointment.DoesNotExist, ValueError):
            return JsonResponse({"ok": False, "error": "Appointment not found."}, status=404)

        if not self.has_change_permission(request, appt):
            return JsonResponse({"ok": False, "error": "Permission denied."}, status=403)

        if master_id:
            # Masters can only move their own appointments and cannot reassign to another tech.
            if hasattr(request.user, "master_profile") and not request.user.is_superuser:
                if str(master_id) != str(request.user.id):
                    return JsonResponse(
                        {"ok": False, "error": "You cannot reassign appointments to a different tech."},
                        status=403,
                    )
            try:
                appt.master = CustomUserDisplay.objects.get(pk=master_id)
            except (CustomUserDisplay.DoesNotExist, ValueError):
                return JsonResponse({"ok": False, "error": "Tech not found."}, status=400)

        try:
            combined = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            return JsonResponse({"ok": False, "error": "Invalid date/time format."}, status=400)

        appt.start_time = make_aware(combined)

        try:
            appt.full_clean()
        except ValidationError as exc:
            if hasattr(exc, "message_dict"):
                msg = "; ".join(
                    f"{field}: {', '.join(msgs)}"
                    for field, msgs in exc.message_dict.items()
                )
            else:
                msg = str(exc)
            return JsonResponse({"ok": False, "error": msg or "Validation failed."}, status=400)

        appt.save()
        return JsonResponse({"ok": True})

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if hasattr(request.user, "master_profile") and not request.user.is_superuser:
            if obj.master_id is None:
                obj.master = request.user


# -----------------------------
# Appointment Status History Admin
# -----------------------------
@admin.register(AppointmentStatusHistory)
class AppointmentStatusHistoryAdmin(ExportCsvMixin,admin.ModelAdmin):
    """
    Admin interface for tracking status changes of appointments.
    """
    exclude = ('set_by',)
    list_display = ('appointment', 'status', 'set_by', 'set_at')
    export_fields = ['appointment', 'status', 'set_by', 'set_at']
    def has_delete_permission(self, request, obj=None):
        # Суперадмин может всегда
        if request.user.is_superuser:
            return True
        # Мастер может удалять
        if hasattr(request.user, "master_profile"):
            return True
        return False
    def save_model(self, request, obj, form, change):
        if not obj.set_by_id:
            obj.set_by = request.user
        super().save_model(request, obj, form, change)


# -----------------------------
# Payment Admin
# -----------------------------
@admin.register(Payment)
class PaymentAdmin(ExportCsvMixin ,admin.ModelAdmin):
    """
    Admin interface for payments.
    """
    list_display = (
        'source',
        'amount_with_currency',
        'mode_badge',
        'balance_due_display',
        'method',
        'processor',
        'card_summary',
        'receipt_link',
        'created_at',
    )
    list_filter = ('method', 'payment_mode', 'processor')
    export_fields = [
        'order',
        'appointment',
        'amount',
        'currency',
        'payment_mode',
        'balance_due',
        'method',
        'processor',
        'processor_payment_id',
        'receipt_url',
        'card_brand',
        'card_last4',
        'fee_amount',
        'created_at',
    ]
    search_fields = (
        'appointment__client__first_name', 'appointment__client__last_name',
        'appointment__master__first_name', 'appointment__master__last_name',
        'appointment__service__name',
        'order__customer_name', 'order__email', 'order__phone', 'order__id',
        'processor_payment_id', 'card_last4'
    )
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)

    @admin.display(description="Source", ordering="order__id")
    def source(self, obj):
        if getattr(obj, "order_id", None):
            return f"Order #{obj.order_id}"
        if getattr(obj, "appointment", None):
            return obj.appointment
        return "—"

    @admin.display(description="Amount")
    def amount_with_currency(self, obj):
        amount = (obj.amount or Decimal("0.00")).quantize(Decimal("0.01"))
        curr = obj.currency or ""
        return f"{curr} {amount}"

    @admin.display(description="Paid")
    def mode_badge(self, obj):
        label = obj.get_payment_mode_display() if hasattr(obj, "get_payment_mode_display") else ""
        return label or "—"

    @admin.display(description="Balance due")
    def balance_due_display(self, obj):
        quant = Decimal("0.01")
        if obj.balance_due and obj.balance_due > 0:
            return f"{obj.currency} {(obj.balance_due or Decimal('0.00')).quantize(quant)}"
        if getattr(obj, "order", None) and obj.order.payment_balance_due:
            return f"{obj.currency} {(obj.order.payment_balance_due or Decimal('0.00')).quantize(quant)}"
        return "—"

    @admin.display(description="Card")
    def card_summary(self, obj):
        if obj.card_brand or obj.card_last4:
            brand = obj.card_brand or ""
            last4 = f"•{obj.card_last4}" if obj.card_last4 else ""
            return f"{brand} {last4}".strip()
        return "—"

    @admin.display(description="Receipt")
    def receipt_link(self, obj):
        if obj.receipt_url:
            return format_html('<a href="{}" target="_blank" rel="noopener">View</a>', obj.receipt_url)
        return "—"


# -----------------------------
# Appointment Prepayment Admin
# -----------------------------
@admin.register(AppointmentPrepayment)
class AppointmentPrepaymentAdmin(ExportCsvMixin,admin.ModelAdmin):
    """
    Admin interface for prepayment options tied to appointments.
    """
    list_display = ('appointment', 'option')
    export_fields = ['appointment', 'option']

# -----------------------------
# Hidden Proxy Admin for CustomUserDisplay
# -----------------------------
@admin.register(CustomUserDisplay)
class CustomUserAdmin(admin.ModelAdmin):

    def get_model_perms(self, request):
        # Hide from admin index
        return {}


# -----------------------------
# Service Master Admin
# -----------------------------
@admin.register(ServiceMaster)
class ServiceMasterAdmin(ExportCsvMixin, MasterSelectorMixing, admin.ModelAdmin):
    """
    Admin interface to assign masters to services.
    """
    list_display = ('staff_member', 'service')
    search_fields = ('master__user__first_name', 'master__user__last_name', 'service__name')
    export_fields = ['master', 'service']

    @admin.display(description=STAFF_DISPLAY_NAME, ordering="master__first_name")
    def staff_member(self, obj):
        full_name = obj.master.get_full_name()
        return full_name if full_name else obj.master.username

# -----------------------------
# Service Admin
# -----------------------------
# вверху файла уже должен быть import:
# from django.contrib import admin
# from django.utils.html import format_html
# и ваши миксины ExportCsvMixin, MasterSelectorMixing
# и модель Service

@admin.register(Service)
class ServiceAdmin(ExportCsvMixin, MasterSelectorMixing, admin.ModelAdmin):
    """
    Admin interface for services.
    """
    list_display = ('name', 'pricing_display', 'category', 'duration_min', 'image_preview')
    search_fields = ('name',)
    list_filter = ('category', 'contact_for_estimate')
    export_fields = [
        'name', 'description', 'base_price', 'contact_for_estimate', 'estimate_from_price',
        'category', 'prepayment_option', 'duration_min', 'extra_time_min'
    ]

    # NEW: allow uploading image and show preview; keep previous fields
    fields = (
        'name', 'category', 'description',
        ('base_price', 'contact_for_estimate'), 'estimate_from_price',
        'prepayment_option', 'duration_min', 'extra_time_min',
        'image', 'image_preview',
    )
    readonly_fields = ('image_preview',)

    @admin.display(description="Pricing", ordering="base_price")
    def pricing_display(self, obj):
        if obj.contact_for_estimate:
            if obj.estimate_from_price:
                return format_html(
                    '<span style="font-weight:600;color:#e53935">Contact for estimate</span>'
                    '<br><small>From ${}</small>',
                    obj.estimate_from_price
                )
            return format_html('<span style="font-weight:600;color:#e53935">Contact for estimate</span>')
        if obj.base_price is None:
            return "—"
        return format_html("${}", obj.base_price)

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
    list_display = ('user', 'filename', 'file_type', 'file_size_display', 'uploaded_by', 'uploaded_at')
    fieldsets = (
        (None, {"fields": ('user', 'file', 'description', 'uploaded_by')}),
        ("Metadata", {"fields": ('file_type', 'file_size_display', 'uploaded_at', 'file_preview')}),
    )
    readonly_fields = ('file_type', 'file_size_display', 'uploaded_at', 'file_preview')
    list_filter = (('uploaded_at', DateFieldListFilter), 'file_type')
    search_fields = ('user__first_name', 'user__last_name', 'description')
    ordering = ['-uploaded_at']

    @admin.display(description="File name")
    def filename(self, obj):
        return obj.filename or obj.file.name

    @admin.display(description="Size")
    def file_size_display(self, obj):
        if obj.file_size:
            return filesizeformat(obj.file_size)
        return "—"

    @admin.display(description="Preview")
    def file_preview(self, obj):
        if obj.file:
            return format_html('<a href="{}" target="_blank" rel="noopener">Open file</a>', obj.file.url)
        return "—"


# -----------------------------
# Client Review Admin
# -----------------------------
@admin.register(ClientReview)
class ClientReviewAdmin(ExportCsvMixin ,admin.ModelAdmin):
    list_display = ("appointment", "get_client", "get_master", "rating", "created_at")
    search_fields = ("appointment__client__first_name", "appointment__client__last_name", "comment")
    list_filter = ("rating", "created_at")
    export_fields = ["appointment", "get_client", "get_master", "rating", "created_at"]
    @admin.display(description="Client")
    def get_client(self, obj):
        appt = obj.appointment
        if appt.client_id:
            return appt.client.get_full_name() or appt.client.username or appt.client.email
        return appt.contact_name or "Guest"

    @admin.display(description="Staff")
    def get_master(self, obj):
        return obj.appointment.master.get_full_name()


# -----------------------------
# Landing Page Review Admin
# -----------------------------
@admin.register(LandingPageReview)
class LandingPageReviewAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ("reviewer_name", "page", "rating", "display_order", "is_published", "updated_at")
    list_filter = ("page", "rating", "is_published")
    search_fields = ("reviewer_name", "quote", "reviewer_title")
    ordering = ("page", "display_order", "-updated_at")
    export_fields = [
        "page",
        "reviewer_name",
        "reviewer_title",
        "rating",
        "quote",
        "display_order",
        "is_published",
        "updated_at",
    ]
    list_editable = ("display_order", "is_published")
    fieldsets = (
        (None, {"fields": ("page", "reviewer_name", "reviewer_title", "rating", "quote")}),
        ("Display", {"fields": ("display_order", "is_published")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at")


#-----------------------------
# Discounts Admin
#-----------------------------
@admin.register(ServiceDiscount)
class ServiceDiscountAdmin(ExportCsvMixin ,admin.ModelAdmin):
    list_display = ('service', 'discount_percent', 'start_date', 'end_date', 'is_active')
    list_filter = ('start_date', 'end_date', 'service')
    search_fields = ('service__name',)
    export_fields = ['service', 'discount_percent', 'start_date', 'end_date', 'is_active']
    @admin.display(boolean=True)
    def is_active(self, obj):
        return obj.is_active()

#-----------------------------
# Promocode Admin
#-----------------------------
@admin.register(PromoCode)
class PromoCodeAdmin(ExportCsvMixin ,admin.ModelAdmin):
    list_display = ('code', 'discount_percent', 'start_date', 'end_date',)
    list_filter = ('start_date', 'end_date')

    export_fields = ['code', 'applicable_services', 'discount_percent', 'start_date', 'end_date']

    @admin.display(boolean=True)
    def is_active(self, obj):
        return obj.is_active()


#-----------------------------
# Appointments Promocode Admin
#-----------------------------
@admin.register(AppointmentPromoCode)
class PromoCodeAdmin(ExportCsvMixin ,admin.ModelAdmin):
    list_display = ('appointment', 'promocode')

    export_fields = ['appointment', 'promocode']


# -----------------------------
# Register remaining models directly
# -----------------------------
admin.site.register(Role)
admin.site.register(UserRole)
admin.site.register(AppointmentStatus)
admin.site.register(PaymentMethod)
admin.site.register(ClientSource)
admin.site.register(MasterRoom)
admin.site.register(ServiceCategory)
admin.site.register(PrepaymentOption)
admin.site.register(PaymentStatus)

@admin.register(MasterProfile)
class MasterProfileAdmin(ExportCsvMixin,admin.ModelAdmin):
    add_form = MasterCreateFullForm
    readonly_fields = ['password_display', 'photo_preview']
    export_fields = ["first_name","last_name","email","username" ,"phone","birth_date","profession", 'bio',"work_start", "work_end", "room", "is_staff", "is_superuser", 'is_active']
    
    def get_export_row(self, obj):
        phone = obj.user.userprofile.phone if hasattr(obj, 'user') else ''
        birth_date = obj.user.userprofile.birth_date if hasattr(obj, 'user') else ''


        return [
            obj.user.first_name,
            obj.user.last_name,
            obj.user.email,
            obj.user.username,
            phone,
            birth_date,
            obj.profession,
            obj.bio,
            obj.work_start,
            obj.work_end,
            obj.room,
            obj.user.is_staff,
            obj.user.is_superuser,
            obj.user.is_active,
        ]
    form = MasterCreateFullForm  # на редактирование тоже можно оставить ту же


    list_display = ("get_name", "room", "profession", "work_start", "work_end")

    def get_fieldsets(self, request, obj=None):
        form = self.form(instance=obj if obj else None)
        fields = list(form.fields.keys())

        if 'photo' in fields and 'photo_preview' not in fields:
            fields.insert(fields.index('photo') + 1, 'photo_preview')
            
        if obj:
            # редактирование
            fields = [f for f in fields if f not in ['password1', 'password2', 'password']]  # ← обязательно убрать 'password'
            if 'email' in fields and 'password_display' not in fields:
                fields.insert(fields.index('email') + 1, 'password_display')
            elif 'password_display' not in fields:
                fields.append('password_display')
        else:
            # создание
            fields = [f for f in fields if f != 'password_display']

        return [(None, {'fields': fields})]

    def photo_preview(self, obj):
        if getattr(obj, "photo", None):
            return format_html('<img src="{}" style="max-width:120px;border-radius:8px;"/>', obj.photo.url)
        return "—"
    photo_preview.short_description = "Preview"
    
    def password_display(self, obj):
        from django.utils.html import format_html
        reset_url = f"/admin/auth/user/{obj.user.id}/password/"
        return format_html(
            '<div style="word-break: break-all;">'
            '<strong>algorithm:</strong> pbkdf2_sha256<br>'
            '<strong>hash:</strong> {}<br><br>'
            '<a href="{}" class="button" style="color: #fff; background: #007bff; padding: 4px 8px; text-decoration: none; border-radius: 4px;">Reset password</a>'
            '</div>',
            obj.user.password,
            reset_url
        )
    password_display.short_description = "Password"

    def get_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        # 1. Забираем все текущие разрешения
        user = obj.user
        user.user_permissions.clear()

        # 2. Добавляем только view_appointment
        needed = [
            # Appointment
            "view_appointment", "add_appointment", "change_appointment", "delete_appointment",
            # MasterAvailability (time off)
            "view_masteravailability", "add_masteravailability", "change_masteravailability", "delete_masteravailability",
        ]
        perms = Permission.objects.filter(codename__in=needed)
        user.user_permissions.add(*perms)


def get_price_html(service):
    if service.contact_for_estimate:
        if service.estimate_from_price:
            return format_html(
                '<strong>Contact for estimate</strong><br><small>From ${}</small>',
                service.estimate_from_price,
            )
        return format_html("<strong>Contact for estimate</strong>")
    discount = service.get_active_discount()
    base = service.base_price_amount()
    if discount:
        discounted = service.get_discounted_price()
        return format_html(
            '<span style="text-decoration: line-through; color: grey;">${}</span><br><strong>${}</strong>',
            base,
            discounted
        )
    return format_html("<strong>${}</strong>", base)

GRID_STEP_MINUTES = 15
DEFAULT_START_MINUTES = 6 * 60
DEFAULT_END_MINUTES = 23 * 60
MAX_CALENDAR_MINUTES = (24 * 60) - GRID_STEP_MINUTES
CALENDAR_COLOR_PALETTE = ["#E4D08A", "#EDC2A2", "#CEAEC6", "#A3C1C9", "#C3CEA3", "#E7B3C3"]


def build_slot_times(time_pointer, end_time):
    slot_times = []
    pointer = time_pointer
    while pointer <= end_time:
        slot_times.append(pointer.strftime('%H:%M'))
        pointer += timedelta(minutes=GRID_STEP_MINUTES)
    return slot_times


def _get_master_colors(masters):
    master_ids = [m.id for m in masters]
    return dict(zip(master_ids, cycle(CALENDAR_COLOR_PALETTE)))


def _build_appointment_display(appt, master_color):
    local_start = localtime(appt.start_time)
    service = appt.service
    base_duration = int(getattr(service, "duration_min", 0) or 0)
    extra_duration = int(getattr(service, "extra_time_min", 0) or 0)
    total_minutes = base_duration + extra_duration
    if total_minutes <= 0:
        total_minutes = GRID_STEP_MINUTES
    local_end = local_start + timedelta(minutes=total_minutes)
    last_status = appt.appointmentstatushistory_set.order_by('-set_at').first()
    status_name = last_status.status.name if last_status else "Unknown"

    if service.contact_for_estimate:
        price_value = "Contact for estimate"
        price_discounted = price_value
    else:
        price_discounted = f"${service.get_discounted_price():.2f}"
        price_value = f"${service.base_price_amount():.2f}"

    try:
        appt_promocode = appt.appointmentpromocode
    except AppointmentPromoCode.DoesNotExist:
        appt_promocode = None

    client_name = appt.contact_name or ""
    if not client_name and appt.client_id:
        client_name = appt.client.get_full_name() or appt.client.username or appt.client.email
    client_name = client_name or "Guest"

    phone_value = appt.contact_phone or ""
    if not phone_value and appt.client_id:
        profile = getattr(appt.client, "userprofile", None)
        phone_value = getattr(profile, "phone", "") if profile else ""

    master_name = ""
    if appt.master_id:
        master_name = appt.master.get_full_name()

    return {
        "id": appt.id,
        "url": f"/admin/core/appointment/{appt.id}/change/",
        "client": escape(client_name),
        "phone": escape(phone_value or ""),
        "service": escape(service.name),
        "status": status_name,
        "master": escape(master_name),
        "time_label": f"{local_start.strftime('%I:%M%p').lstrip('0')} - {local_end.strftime('%I:%M%p').lstrip('0')}",
        "time_start": local_start.strftime('%I:%M%p').lstrip('0'),
        "duration": f"{base_duration}min",
        "discount": f"-{appt_promocode.promocode.discount_percent}" if appt_promocode else "",
        "price_discounted": price_discounted,
        "price": price_value,
        "background": master_color or CALENDAR_COLOR_PALETTE[0],
        "start_minutes": _time_to_minutes(local_start.time()),
    }


def build_week_table(week_dates, slot_times, appointments, masters):
    master_colors = _get_master_colors(masters)
    appointments_by_slot = {}

    week_set = set(week_dates)
    for appt in appointments:
        local_start = localtime(appt.start_time)
        appt_date = local_start.date()
        if appt_date not in week_set:
            continue
        time_key = local_start.strftime('%H:%M')
        appt_display = _build_appointment_display(appt, master_colors.get(appt.master_id))
        appointments_by_slot.setdefault(appt_date, {}).setdefault(time_key, []).append(appt_display)

    for day_map in appointments_by_slot.values():
        for time_key in day_map:
            day_map[time_key].sort(key=lambda item: item["start_minutes"])

    week_table = []
    for time_str in slot_times:
        row = {"time": time_str, "cells": []}
        for day in week_dates:
            row["cells"].append({
                "date": day,
                "appointments": appointments_by_slot.get(day, {}).get(time_str, []),
            })
        week_table.append(row)
    return week_table


def build_month_grid(range_start_date, range_end_date, focus_month, appointments, masters):
    master_colors = _get_master_colors(masters)
    appointments_by_day = {}

    for appt in appointments:
        local_start = localtime(appt.start_time)
        appt_date = local_start.date()
        if appt_date < range_start_date or appt_date > range_end_date:
            continue
        appt_display = _build_appointment_display(appt, master_colors.get(appt.master_id))
        appointments_by_day.setdefault(appt_date, []).append(appt_display)

    for day, items in appointments_by_day.items():
        items.sort(key=lambda item: item["start_minutes"])

    month_grid = []
    pointer = range_start_date
    while pointer <= range_end_date:
        week = []
        for _ in range(7):
            items = appointments_by_day.get(pointer, [])
            week.append({
                "date": pointer,
                "in_month": pointer.month == focus_month,
                "appointments": items[:3],
                "overflow": max(0, len(items) - 3),
            })
            pointer += timedelta(days=1)
        month_grid.append(week)
    return month_grid


def _time_to_minutes(value):
    return value.hour * 60 + value.minute


def _floor_to_slot(minutes: int) -> int:
    minutes = max(minutes, 0)
    return (minutes // GRID_STEP_MINUTES) * GRID_STEP_MINUTES


def _ceil_to_slot(minutes: int) -> int:
    minutes = max(minutes, 0)
    minutes = min(minutes, MAX_CALENDAR_MINUTES)
    remainder = minutes % GRID_STEP_MINUTES
    if remainder:
        minutes += GRID_STEP_MINUTES - remainder
        minutes = min(minutes, MAX_CALENDAR_MINUTES)
    return minutes


def determine_calendar_window(masters, appointments):
    """
    Expands the calendar grid to cover the earliest start / latest end time for masters or appointments.
    """
    start_candidates = []
    end_candidates = []

    for master in masters:
        profile = getattr(master, "master_profile", None)
        if not profile:
            continue
        if profile.work_start:
            start_candidates.append(_time_to_minutes(profile.work_start))
        if profile.work_end:
            end_minutes = _time_to_minutes(profile.work_end)
            if profile.work_end <= profile.work_start:
                end_minutes = MAX_CALENDAR_MINUTES
            end_candidates.append(end_minutes)

    for appt in appointments:
        local_start = localtime(appt.start_time)
        start_candidates.append(_time_to_minutes(local_start.time()))
        base_duration = appt.service.duration_min or 0
        extra_duration = appt.service.extra_time_min or 0
        total_minutes = base_duration + extra_duration
        if total_minutes <= 0:
            total_minutes = GRID_STEP_MINUTES
        local_end = local_start + timedelta(minutes=total_minutes)
        if local_end.date() != local_start.date():
            end_minutes = MAX_CALENDAR_MINUTES
        else:
            end_minutes = _time_to_minutes(local_end.time())
        end_candidates.append(end_minutes)

    start_minutes = _floor_to_slot(min(start_candidates) if start_candidates else DEFAULT_START_MINUTES)
    end_minutes = _ceil_to_slot(max(end_candidates) if end_candidates else DEFAULT_END_MINUTES)
    if end_minutes <= start_minutes:
        end_minutes = min(start_minutes + GRID_STEP_MINUTES, MAX_CALENDAR_MINUTES)

    base = datetime(2000, 1, 1)
    return base + timedelta(minutes=start_minutes), base + timedelta(minutes=end_minutes)


def createTable(selected_date, time_pointer, end_time, slot_times, appointments, masters, availabilities):
    MASTER_COLORS = _get_master_colors(masters)


    grid_start_dt = time_pointer
    grid_end_dt = end_time
    pointer = time_pointer
    while pointer <= end_time:
        slot_times.append(pointer.strftime('%H:%M'))
        pointer += timedelta(minutes=15)

    slot_map = {}
    skip_map = {}

    # --- Appointments ---
    for appt in appointments:
        local_start = localtime(appt.start_time)
        if local_start.date() != selected_date:
            continue  # 💥 вот тут должен быть continue до skip_map

        master_id = appt.master_id
        time_key = local_start.strftime('%H:%M')
        service = appt.service
        base_duration = int(getattr(service, "duration_min", 0) or 0)
        extra_duration = int(getattr(service, "extra_time_min", 0) or 0)
        duration = base_duration + extra_duration
        rowspan = max(1, duration // 15)

        slot_map.setdefault(master_id, {})
        skip_map.setdefault(master_id, {})

        slot_map[master_id][time_key] = {
            "appointment": appt,
            "rowspan": rowspan,
            "base_duration": base_duration,
            "extra_duration": extra_duration,
        }

        for i in range(1, rowspan):
            t = local_start + timedelta(minutes=i * 15)
            skip_map[master_id][t.strftime('%H:%M')] = True

    # --- Vacations / Breaks ---

    availability_map = {}

    grid_start_minutes = grid_start_dt.hour * 60 + grid_start_dt.minute
    grid_end_minutes = grid_end_dt.hour * 60 + grid_end_dt.minute
    buffered_end_minutes = min(grid_end_minutes + GRID_STEP_MINUTES, MAX_CALENDAR_MINUTES)

    for period in availabilities:
        master_id = int(getattr(period.master, "id", period.master))
        start = localtime(period.start_time)
        end = localtime(period.end_time)

        if start.date() <= selected_date <= end.date():
            day_start_naive = datetime.combine(selected_date, time(0, 0)) + timedelta(minutes=grid_start_minutes)
            day_end_naive = datetime.combine(selected_date, time(0, 0)) + timedelta(minutes=buffered_end_minutes)
            day_start = day_start_naive.replace(tzinfo=start.tzinfo)
            day_end = day_end_naive.replace(tzinfo=end.tzinfo)

            block_start = max(start, day_start)
            block_end = min(end, day_end)

            total_minutes = int((block_end - block_start).total_seconds() // 60)
            rowspan = max(1, total_minutes // 15)

            # Найдём слот начала: ближайший к block_start
            slot_str = block_start.strftime('%H:%M')
            i = bisect_left(slot_times, slot_str)
            available_slots = slot_times[i:i+rowspan]

            # Найдём первый незанятый слот для отрисовки Vacation
            skip_map.setdefault(master_id, {})
            slot_map_for_master = slot_map.get(master_id, {})
            availability_map.setdefault(master_id, {})

            start_slot = None
            for candidate in available_slots:
                if candidate not in skip_map[master_id] and candidate not in slot_map_for_master:
                    start_slot = candidate
                    break

            if start_slot:

                availability_map[master_id][start_slot] = {
                    "rowspan": rowspan,
                    "reason": period.reason,
                    "start": block_start.strftime("%I:%M%p").lstrip('0'),
                    "end": block_end.strftime("%I:%M%p").lstrip('0'),
                    "until": period.end_time.strftime("%d %b %Y"),
                    "availability_id": period.id,
                }

            # Помечаем все остальные как skip
            for j in range(rowspan):
                t = block_start + timedelta(minutes=j * 15)
                skip_key = t.strftime('%H:%M')
                skip_map[master_id][skip_key] = True

    # --- Table build ---

    calendar_table = []
    for time_index, time_str in enumerate(slot_times):
        row = {"time": time_str, "cells": []}
        for master in masters:
            master_id = master.id


            if master_id in slot_map and time_str in slot_map[master_id]:
                data = slot_map[master_id][time_str]
                appt = data["appointment"]
                try:
                    appt_promocode = appt.appointmentpromocode
                except AppointmentPromoCode.DoesNotExist:
                    appt_promocode = None

                local_start = localtime(appt.start_time)
                base_duration = data.get("base_duration", 0) or 0
                extra_duration = data.get("extra_duration", 0) or 0
                local_end = local_start + timedelta(minutes=base_duration + extra_duration)
                last_status = appt.appointmentstatushistory_set.order_by('-set_at').first()
                status_name = last_status.status.name if last_status else "Unknown"
                service_obj = appt.service
                if service_obj.contact_for_estimate:
                    price_value = "Contact for estimate"
                    price_discounted = price_value
                else:
                    price_discounted = f"${service_obj.get_discounted_price():.2f}"
                    price_value = f"${service_obj.base_price_amount():.2f}"

                client_name = appt.contact_name or ""
                if not client_name and appt.client_id:
                    client_name = appt.client.get_full_name() or appt.client.username or appt.client.email
                client_name = client_name or "Guest"

                phone_value = appt.contact_phone or ""
                if not phone_value and appt.client_id:
                    profile = getattr(appt.client, "userprofile", None)
                    phone_value = getattr(profile, "phone", "") if profile else ""

                row["cells"].append({
                    "html": f"""
                                        <div>
                                            <div style="font-size:0.75rem;">
                                                {local_start.strftime('%I:%M').lstrip('0')} – {local_end.strftime('%I:%M').lstrip('0')}
                                                <strong>{escape(client_name)}</strong>
                                            </div>
                                            <div style="font-size:0.75rem;">
                                                {escape(appt.service.name)}
                                            </div>
                                        </div>
                                    """,
                    "rowspan": data["rowspan"],
                    "appt_id": appt.id,
                    "appointment": appt,
                    "client": escape(client_name),
                    "phone": escape(phone_value or ""),
                    "service": escape(appt.service.name),
                    "status": status_name,
                    "master": escape(master.get_full_name()),
                    "time_label": f"{local_start.strftime('%I:%M%p').lstrip('0')} - {local_end.strftime('%I:%M%p').lstrip('0')}",
                    "duration": f"{base_duration}min",
                    "discount": f"-{appt_promocode.promocode.discount_percent}" if appt_promocode else "",
                    "price_discounted": price_discounted,
                    "price": price_value,
                    "background": MASTER_COLORS.get(master_id),
                })

            elif master_id in availability_map and time_str in availability_map[master_id]:
                data = availability_map[master_id][time_str]
                row["cells"].append({
                    "html": data["reason"].capitalize(),
                    "rowspan": data["rowspan"],
                    "unavailable": True,
                    "reason": data["reason"],
                    "start": data["start"],
                    "end": data["end"],
                    "until": data["until"],
                    "availability_id": data["availability_id"],
                })
            elif master_id in skip_map and time_str in skip_map[master_id]:
                row["cells"].append({"skip": True})
            else:
                row["cells"].append({
                    "html": '',
                    "rowspan": 1,
                    "master_id": master_id,
                })


        calendar_table.append(row)

    return calendar_table

from django.contrib import admin
from django.utils import timezone
from core.models import DealerApplication, DealerTierLevel, UserProfile


@admin.register(DealerTierLevel)
class DealerTierLevelAdmin(admin.ModelAdmin):
    list_display = ("label", "code", "discount_percent", "minimum_spend", "is_active")
    list_editable = ("discount_percent", "minimum_spend", "is_active")
    search_fields = ("label", "code")
    ordering = ("minimum_spend", "sort_order")
    fieldsets = (
        (None, {"fields": ("label", "code", "description")}),
        ("Eligibility", {"fields": ("minimum_spend", "discount_percent", "sort_order", "is_active")}),
    )

# ──────────────────────────────────────────────────────────────────────────────
# Dealer Applications
# ──────────────────────────────────────────────────────────────────────────────

@admin.register(DealerApplication)
class DealerApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "user", "business_name", "status",
        "preferred_tier_display", "assigned_tier_display",
        "created_at", "reviewed_by", "reviewed_at",
    )
    list_filter = ("status", "preferred_tier", "assigned_tier", "created_at")
    search_fields = ("user__email", "user__username", "business_name", "phone", "website")
    readonly_fields = ("created_at", "reviewed_at", "reviewed_by")
    fieldsets = (
        ("Application", {
            "fields": (
                "user", "business_name", "website", "phone",
                "preferred_tier", "notes",
            )
        }),
        ("Review", {
            "fields": (
                "status", "assigned_tier", "internal_note",
                "reviewed_by", "reviewed_at", "created_at",
            )
        }),
    )

    actions = ["approve_selected", "reject_selected"]

    @admin.display(description="Requested tier")
    def preferred_tier_display(self, obj):
        return obj.get_preferred_tier_display() or "—"

    @admin.display(description="Assigned tier")
    def assigned_tier_display(self, obj):
        return obj.get_assigned_tier_display() or "—"

    @admin.action(description="Approve selected applications")
    def approve_selected(self, request, queryset):
        count = 0
        for app in queryset.select_related("user"):
            if app.status != DealerApplication.Status.APPROVED:
                app.approve(admin_user=request.user)
                count += 1
        self.message_user(request, f"Approved {count} application(s).")

    @admin.action(description="Reject selected applications")
    def reject_selected(self, request, queryset):
        count = 0
        for app in queryset:
            if app.status != DealerApplication.Status.REJECTED:
                app.reject(admin_user=request.user)
                count += 1
        self.message_user(request, f"Rejected {count} application(s).")


# ──────────────────────────────────────────────────────────────────────────────
# Dealers (UserProfile)
# ──────────────────────────────────────────────────────────────────────────────

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user", "is_dealer", "dealer_tier", "dealer_since",
        "total_spent_display", "dealer_discount_display",
    )
    list_filter = ("is_dealer", "dealer_tier")
    search_fields = ("user__email", "user__username")
    readonly_fields = ("dealer_since",)

    fieldsets = (
        ("User", {"fields": ("user",)}),
        ("Dealer", {"fields": ("is_dealer", "dealer_tier", "dealer_since")}),
        # добавьте ваши остальные поля профиля при необходимости
    )

    @admin.display(description="Total spent")
    def total_spent_display(self, obj):
        try:
            return format_currency(obj.total_spent_cad())
        except Exception:
            return format_currency(0)

    @admin.display(description="Dealer discount")
    def dealer_discount_display(self, obj):
        try:
            return f"{obj.dealer_discount_percent}%"
        except Exception:
            return "0%"

    actions = ["recompute_tiers"]

    @admin.action(description="Recompute dealer tiers")
    def recompute_tiers(self, request, queryset):
        for up in queryset.select_related("user"):
            up.recompute_dealer_tier()
            if up.is_dealer and not up.dealer_since:
                up.dealer_since = timezone.now()
            up.save(update_fields=["dealer_tier", "dealer_since"])
        self.message_user(request, f"Recomputed tiers for {queryset.count()} profile(s).")


@admin.register(FontPreset)
class FontPresetAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "font_family",
        "source_kind",
        "mime_type",
        "preload",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active", "preload", "font_style")
    search_fields = ("name", "slug", "font_family", "static_path", "notes")
    readonly_fields = ("created_at", "updated_at", "preview")
    fieldsets = (
        ("Identity", {"fields": ("name", "slug", "font_family", "fallback_stack", "notes")}),
        ("Loading", {
            "fields": (
                "static_path",
                "font_file",
                "mime_type",
                "font_weight",
                "font_style",
                "font_display",
                "preload",
                "is_active",
                "preview",
            )
        }),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Source", ordering="static_path")
    def source_kind(self, obj):
        if obj.font_file:
            return "Upload"
        if obj.static_path:
            return "Static"
        return "—"

    @admin.display(description="Preview")
    def preview(self, obj):
        if not obj or not obj.url:
            return "Provide a file or static path to preview."
        face = (
            f"@font-face{{font-family:'{obj.font_family}';"
            f"src:url('{obj.url}') format('{obj.format_hint}');"
            f"font-weight:{obj.font_weight};font-style:{obj.font_style};"
            f"font-display:{obj.font_display};}}"
        )
        sample = (
            f"<div style=\"font-family:{obj.font_stack};font-size:18px;"
            f"padding:4px 0;\">The quick brown fox jumps over the lazy dog.</div>"
        )
        return format_html("<style>{}</style>{}", mark_safe(face), mark_safe(sample))


@admin.register(PageFontSetting)
class PageFontSettingAdmin(admin.ModelAdmin):
    form = PageFontSettingAdminForm
    list_display = (
        "page",
        "body_font",
        "heading_font",
        "ui_font_display",
        "updated_at",
    )
    list_filter = ("page",)
    search_fields = ("notes",)
    readonly_fields = ("created_at", "updated_at", "preview")
    fieldsets = (
        ("Page", {"fields": ("page",)}),
        ("Fonts", {"fields": ("body_font", "heading_font", "ui_font")}),
        ("Notes", {"fields": ("notes",)}),
        ("Preview", {"fields": ("preview",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="UI font")
    def ui_font_display(self, obj):
        if not obj:
            return "—"
        return obj.resolved_ui_font

    @admin.display(description="Preview")
    def preview(self, obj):
        if not obj:
            return "Save to preview."
        fonts = [obj.body_font, obj.heading_font, obj.resolved_ui_font]
        faces = []
        for font in fonts:
            if not font or not font.url:
                continue
            faces.append(
                f"@font-face{{font-family:'{font.font_family}';"
                f"src:url('{font.url}') format('{font.format_hint}');"
                f"font-weight:{font.font_weight};"
                f"font-style:{font.font_style};"
                f"font-display:{font.font_display};}}"
            )
        face_block = "".join(faces)
        heading = (
            f"<div style=\"font-family:{obj.heading_font.font_stack};"
            f"font-size:20px;font-weight:800;padding:6px 0 2px;\">"
            f"Heading sample — Wheel &amp; Tire Service</div>"
        )
        body = (
            f"<div style=\"font-family:{obj.body_font.font_stack};"
            f"font-size:16px;padding:4px 0;\">"
            f"Body sample — The quick brown fox jumps over the lazy dog.</div>"
        )
        ui = (
            f"<div style=\"font-family:{obj.resolved_ui_font.font_stack};"
            f"font-size:14px;text-transform:uppercase;padding:4px 0;\">"
            f"UI sample — Buttons &amp; navigation</div>"
        )
        preview_block = "".join([heading, body, ui])
        return format_html("<style>{}</style>{}", mark_safe(face_block), mark_safe(preview_block))


class TopbarSettingsAdminForm(forms.ModelForm):
    NAV_SIZE_PRESETS = {
        "sm": "0.9rem",
        "md": "1.05rem",
        "lg": "1.2rem",
        "xl": "1.35rem",
        "xxl": "1.5rem",
        "xxxl": "1.65rem",
    }
    BRAND_SIZE_PRESETS = {
        "sm": "clamp(1.1rem, 1.8vw, 1.5rem)",
        "md": "clamp(1.25rem, 2.1vw, 1.7rem)",
        "lg": "clamp(1.35rem, 2.4vw, 1.9rem)",
        "xl": "clamp(1.5rem, 2.8vw, 2.1rem)",
        "xxl": "clamp(1.6rem, 3.1vw, 2.35rem)",
        "xxxl": "clamp(1.75rem, 3.5vw, 2.6rem)",
    }
    TAGLINE_SIZE_PRESETS = {
        "sm": "0.85em",
        "md": "1em",
        "lg": "1.15em",
        "xl": "1.3em",
        "xxl": "1.45em",
        "xxxl": "1.6em",
    }

    SIZE_CHOICES = (
        ("sm", "Small"),
        ("md", "Medium (default)"),
        ("lg", "Large"),
        ("xl", "Extra large"),
        ("xxl", "2x large"),
        ("xxxl", "3x large"),
        ("custom", "Custom (leave as-is)"),
    )

    nav_size_desktop_preset = forms.ChoiceField(
        label="Menu size (desktop)",
        choices=SIZE_CHOICES,
        required=True,
        help_text="Pick a preset without CSS. Custom does not change the value below.",
    )
    brand_size_desktop_preset = forms.ChoiceField(
        label="Brand size (desktop)",
        choices=SIZE_CHOICES,
        required=True,
        help_text="Quick size selection for the brand text.",
    )
    tagline_word_1_size_preset = forms.ChoiceField(
        label="Tagline word 1 size (easy)",
        choices=SIZE_CHOICES,
        required=True,
        help_text="Pick a preset size. Custom keeps the manual CSS value below.",
    )
    tagline_word_2_size_preset = forms.ChoiceField(
        label="Tagline word 2 size (easy)",
        choices=SIZE_CHOICES,
        required=True,
        help_text="Pick a preset size. Custom keeps the manual CSS value below.",
    )
    tagline_word_3_size_preset = forms.ChoiceField(
        label="Tagline word 3 size (easy)",
        choices=SIZE_CHOICES,
        required=True,
        help_text="Pick a preset size. Custom keeps the manual CSS value below.",
    )

    class Meta:
        model = TopbarSettings
        fields = "__all__"
        labels = {
            "tagline_word_1_text": "Tagline word 1",
            "tagline_word_2_text": "Tagline word 2",
            "tagline_word_3_text": "Tagline word 3",
        }
        help_texts = {
            "tagline_word_1_text": "If set, replaces the first word in the tagline.",
            "tagline_word_2_text": "If set, replaces the second word in the tagline.",
            "tagline_word_3_text": "If set, replaces the third word in the tagline.",
        }

    def _preset_for_value(self, value, preset_map):
        if not value:
            return "custom"
        normalized = str(value).strip()
        for key, preset_value in preset_map.items():
            if normalized == preset_value:
                return key
        return "custom"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        nav_value = getattr(self.instance, "nav_size_desktop", None)
        brand_value = getattr(self.instance, "brand_size_desktop", None)
        tag1_value = getattr(self.instance, "tagline_word_1_size", None)
        tag2_value = getattr(self.instance, "tagline_word_2_size", None)
        tag3_value = getattr(self.instance, "tagline_word_3_size", None)
        self.fields["nav_size_desktop_preset"].initial = self._preset_for_value(
            nav_value,
            self.NAV_SIZE_PRESETS,
        )
        self.fields["brand_size_desktop_preset"].initial = self._preset_for_value(
            brand_value,
            self.BRAND_SIZE_PRESETS,
        )
        self.fields["tagline_word_1_size_preset"].initial = self._preset_for_value(
            tag1_value,
            self.TAGLINE_SIZE_PRESETS,
        )
        self.fields["tagline_word_2_size_preset"].initial = self._preset_for_value(
            tag2_value,
            self.TAGLINE_SIZE_PRESETS,
        )
        self.fields["tagline_word_3_size_preset"].initial = self._preset_for_value(
            tag3_value,
            self.TAGLINE_SIZE_PRESETS,
        )

    def save(self, commit=True):
        obj = super().save(commit=False)
        nav_preset = self.cleaned_data.get("nav_size_desktop_preset")
        brand_preset = self.cleaned_data.get("brand_size_desktop_preset")
        tag1_preset = self.cleaned_data.get("tagline_word_1_size_preset")
        tag2_preset = self.cleaned_data.get("tagline_word_2_size_preset")
        tag3_preset = self.cleaned_data.get("tagline_word_3_size_preset")

        if nav_preset in self.NAV_SIZE_PRESETS:
            obj.nav_size_desktop = self.NAV_SIZE_PRESETS[nav_preset]
        if brand_preset in self.BRAND_SIZE_PRESETS:
            obj.brand_size_desktop = self.BRAND_SIZE_PRESETS[brand_preset]
        if tag1_preset in self.TAGLINE_SIZE_PRESETS:
            obj.tagline_word_1_size = self.TAGLINE_SIZE_PRESETS[tag1_preset]
        if tag2_preset in self.TAGLINE_SIZE_PRESETS:
            obj.tagline_word_2_size = self.TAGLINE_SIZE_PRESETS[tag2_preset]
        if tag3_preset in self.TAGLINE_SIZE_PRESETS:
            obj.tagline_word_3_size = self.TAGLINE_SIZE_PRESETS[tag3_preset]

        if commit:
            obj.save()
            self.save_m2m()
        return obj


@admin.register(TopbarSettings)
class TopbarSettingsAdmin(admin.ModelAdmin):
    list_display = ("label", "updated_at")
    readonly_fields = ("preview", "created_at", "updated_at")
    form = TopbarSettingsAdminForm
    fieldsets = (
        ("Preview", {"fields": ("preview",)}),
        ("Fonts", {"fields": ("brand_font", "brand_word_white_font", "brand_word_middle_font", "brand_word_red_font", "nav_font", "tagline_word_1_font", "tagline_word_2_font", "tagline_word_3_font")}),
        ("Sizing (easy)", {"fields": ("brand_size_desktop_preset", "nav_size_desktop_preset")}),
        ("Sizing (advanced)", {"fields": ("brand_size_desktop", "nav_size", "nav_size_desktop", "padding_y_desktop"), "classes": ("collapse",)}),
        ("Layout", {"fields": ("order_brand", "order_tagline", "order_nav")}),
        ("Brand styling", {"fields": ("brand_weight", "brand_letter_spacing", "brand_transform")}),
        ("Brand word styles", {"fields": ("brand_word_1_color", "brand_word_2_color", "brand_word_3_color", "brand_word_1_size", "brand_word_2_size", "brand_word_3_size", "brand_word_1_weight", "brand_word_2_weight", "brand_word_3_weight", "brand_word_1_style", "brand_word_2_style", "brand_word_3_style")}),
        ("Tagline (words + styles)", {
            "fields": (
                "tagline_word_1_text",
                "tagline_word_2_text",
                "tagline_word_3_text",
                "tagline_word_1_color",
                "tagline_word_2_color",
                "tagline_word_3_color",
                "tagline_word_1_size_preset",
                "tagline_word_2_size_preset",
                "tagline_word_3_size_preset",
                "tagline_word_1_size",
                "tagline_word_2_size",
                "tagline_word_3_size",
                "tagline_word_1_weight",
                "tagline_word_2_weight",
                "tagline_word_3_weight",
                "tagline_word_1_style",
                "tagline_word_2_style",
                "tagline_word_3_style",
            )
        }),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Topbar settings")
    def label(self, obj):
        return "Topbar settings"

    @admin.display(description="Topbar preview")
    def preview(self, obj):
        if not obj:
            return ""

        def stack(font, fallback):
            return font.font_stack if font else fallback

        brand_stack = stack(obj.brand_font, '"Inter", system-ui, sans-serif')
        word1_stack = stack(obj.brand_word_white_font, brand_stack)
        word2_stack = stack(obj.brand_word_middle_font, brand_stack)
        word3_stack = stack(obj.brand_word_red_font, brand_stack)
        nav_stack = stack(obj.nav_font, '"Inter", system-ui, sans-serif')
        tag1_stack = stack(obj.tagline_word_1_font, nav_stack)
        tag2_stack = stack(obj.tagline_word_2_font, nav_stack)
        tag3_stack = stack(obj.tagline_word_3_font, nav_stack)

        def face_block(font):
            if not font or not font.url:
                return ""
            return (
                "@font-face{"
                f"font-family:\"{font.font_family}\";"
                f"src:url(\"{font.url}\") format(\"{font.format_hint}\");"
                f"font-weight:{font.font_weight};"
                f"font-style:{font.font_style};"
                f"font-display:{font.font_display};"
                "}"
            )

        faces = "".join(
            face_block(font)
            for font in (
                obj.brand_font,
                obj.brand_word_white_font,
                obj.brand_word_middle_font,
                obj.brand_word_red_font,
                obj.nav_font,
                obj.tagline_word_1_font,
                obj.tagline_word_2_font,
                obj.tagline_word_3_font,
            )
        )

        preview_style = f"""
        {faces}
        .topbar-preview{{
          display:flex;
          align-items:center;
          gap:20px;
          padding:12px 16px;
          background:#050505;
          border:1px solid rgba(255,255,255,.12);
          border-radius:12px;
          color:#fff;
        }}
        .topbar-preview__brand{{
          display:flex;
          align-items:baseline;
          gap:.45rem;
          font-family:{brand_stack};
          font-size:{obj.brand_size_desktop or "1.35rem"};
          font-weight:{obj.brand_weight or "800"};
          letter-spacing:{obj.brand_letter_spacing or ".06em"};
          text-transform:{obj.brand_transform or "uppercase"};
        }}
        .topbar-preview__brand span{{line-height:1;}}
        .topbar-preview__brand .word-1{{
          color:{obj.brand_word_1_color or "#fff"};
          font-family:{word1_stack};
          font-size:{obj.brand_word_1_size or "inherit"};
          font-weight:{obj.brand_word_1_weight or "inherit"};
          font-style:{obj.brand_word_1_style or "normal"};
        }}
        .topbar-preview__brand .word-2{{
          color:{obj.brand_word_2_color or "#fff"};
          font-family:{word2_stack};
          font-size:{obj.brand_word_2_size or "inherit"};
          font-weight:{obj.brand_word_2_weight or "inherit"};
          font-style:{obj.brand_word_2_style or "normal"};
        }}
        .topbar-preview__brand .word-3{{
          color:{obj.brand_word_3_color or "#d50000"};
          font-family:{word3_stack};
          font-size:{obj.brand_word_3_size or "inherit"};
          font-weight:{obj.brand_word_3_weight or "inherit"};
          font-style:{obj.brand_word_3_style or "normal"};
        }}
        .topbar-preview__tagline{{
          display:flex;
          align-items:center;
          gap:.5rem;
          font-family:{nav_stack};
          font-size:.85rem;
          letter-spacing:.2em;
          text-transform:uppercase;
          color:rgba(255,255,255,.7);
          white-space:nowrap;
        }}
        .topbar-preview__tagline .tag-1{{
          color:{obj.tagline_word_1_color or "rgba(255,255,255,.7)"};
          font-family:{tag1_stack};
          font-size:{obj.tagline_word_1_size or "inherit"};
          font-weight:{obj.tagline_word_1_weight or "800"};
          font-style:{obj.tagline_word_1_style or "normal"};
        }}
        .topbar-preview__tagline .tag-2{{
          color:{obj.tagline_word_2_color or "rgba(255,255,255,.7)"};
          font-family:{tag2_stack};
          font-size:{obj.tagline_word_2_size or "inherit"};
          font-weight:{obj.tagline_word_2_weight or "800"};
          font-style:{obj.tagline_word_2_style or "normal"};
        }}
        .topbar-preview__tagline .tag-3{{
          color:{obj.tagline_word_3_color or "rgba(255,255,255,.7)"};
          font-family:{tag3_stack};
          font-size:{obj.tagline_word_3_size or "inherit"};
          font-weight:{obj.tagline_word_3_weight or "800"};
          font-style:{obj.tagline_word_3_style or "normal"};
        }}
        .topbar-preview__nav{{
          margin-left:auto;
          display:flex;
          align-items:center;
          gap:1rem;
          font-family:{nav_stack};
          font-size:{obj.nav_size_desktop or ".95rem"};
          text-transform:uppercase;
          letter-spacing:.08em;
          color:rgba(255,255,255,.78);
        }}
        .topbar-preview__nav span{{padding:.2rem .4rem;border-radius:.5rem;}}
        """

        tag1_text = (obj.tagline_word_1_text or "").strip()
        tag2_text = (obj.tagline_word_2_text or "").strip()
        tag3_text = (obj.tagline_word_3_text or "").strip()
        if not (tag1_text or tag2_text or tag3_text):
            tag1_text = "CUSTOM BUILDS"
            tag2_text = "INSTALLS"
            tag3_text = "UPGRADES"

        def _tag_span(cls_name: str, text: str) -> str:
            return f'<span class="{cls_name}">{escape(text)}</span>'

        tagline_parts = []
        if tag1_text:
            tagline_parts.append(_tag_span("tag-1", tag1_text))
        if tag1_text and tag2_text:
            tagline_parts.append("<span>•</span>")
        if tag2_text:
            tagline_parts.append(_tag_span("tag-2", tag2_text))
        if (tag1_text or tag2_text) and tag3_text:
            tagline_parts.append("<span>•</span>")
        if tag3_text:
            tagline_parts.append(_tag_span("tag-3", tag3_text))

        preview_markup = f"""
        <div class="topbar-preview">
          <div class="topbar-preview__brand">
            <span class="word-1">BAD</span>
            <span class="word-2">GUY</span>
            <span class="word-3">MOTORS</span>
          </div>
          <div class="topbar-preview__tagline">
            {''.join(tagline_parts)}
          </div>
          <div class="topbar-preview__nav">
            <span>Services</span>
            <span>Products</span>
            <span>Merch</span>
          </div>
        </div>
        """
        return format_html("<style>{}</style>{}", mark_safe(preview_style), mark_safe(preview_markup))

    def has_add_permission(self, request):
        if TopbarSettings.objects.exists():
            return False
        return super().has_add_permission(request)


@admin.register(LegalPage)
class LegalPageAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("title", "slug", "body")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("title", "slug", "body", "is_active")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(AdminLoginBranding)
class AdminLoginBrandingAdmin(admin.ModelAdmin):
    list_display = ("label", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Logo", {"fields": ("login_logo", "login_logo_dark", "login_logo_alt")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        if AdminLoginBranding.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Page")
    def label(self, obj):
        return "Admin login"


class PageSectionAdminForm(forms.ModelForm):
    config_title = forms.CharField(label="Title", required=False)
    config_body = forms.CharField(
        label="Body",
        required=False,
        widget=CKEditorUploadingWidget(config_name="pagecopy"),
    )
    config_cta_label = forms.CharField(label="CTA label", required=False)
    config_cta_url = forms.CharField(label="CTA url", required=False)
    config_image_url = forms.CharField(label="Image url", required=False)
    config_image_alt = forms.CharField(label="Image alt text", required=False)

    config_gallery_image_1_url = forms.CharField(label="Gallery image 1 url", required=False)
    config_gallery_image_1_alt = forms.CharField(label="Gallery image 1 alt", required=False)
    config_gallery_image_2_url = forms.CharField(label="Gallery image 2 url", required=False)
    config_gallery_image_2_alt = forms.CharField(label="Gallery image 2 alt", required=False)
    config_gallery_image_3_url = forms.CharField(label="Gallery image 3 url", required=False)
    config_gallery_image_3_alt = forms.CharField(label="Gallery image 3 alt", required=False)
    config_gallery_image_4_url = forms.CharField(label="Gallery image 4 url", required=False)
    config_gallery_image_4_alt = forms.CharField(label="Gallery image 4 alt", required=False)
    config_gallery_image_5_url = forms.CharField(label="Gallery image 5 url", required=False)
    config_gallery_image_5_alt = forms.CharField(label="Gallery image 5 alt", required=False)
    config_gallery_image_6_url = forms.CharField(label="Gallery image 6 url", required=False)
    config_gallery_image_6_alt = forms.CharField(label="Gallery image 6 alt", required=False)

    config_faq_1_question = forms.CharField(label="FAQ 1 question", required=False)
    config_faq_1_answer = forms.CharField(
        label="FAQ 1 answer",
        required=False,
        widget=CKEditorUploadingWidget(config_name="pagecopy"),
    )
    config_faq_2_question = forms.CharField(label="FAQ 2 question", required=False)
    config_faq_2_answer = forms.CharField(
        label="FAQ 2 answer",
        required=False,
        widget=CKEditorUploadingWidget(config_name="pagecopy"),
    )
    config_faq_3_question = forms.CharField(label="FAQ 3 question", required=False)
    config_faq_3_answer = forms.CharField(
        label="FAQ 3 answer",
        required=False,
        widget=CKEditorUploadingWidget(config_name="pagecopy"),
    )
    config_faq_4_question = forms.CharField(label="FAQ 4 question", required=False)
    config_faq_4_answer = forms.CharField(
        label="FAQ 4 answer",
        required=False,
        widget=CKEditorUploadingWidget(config_name="pagecopy"),
    )

    config_custom_html = forms.CharField(
        label="Custom HTML",
        required=False,
        widget=CKEditorUploadingWidget(config_name="pagecopy"),
    )

    class Meta:
        model = PageSection
        fields = (
            "section_type",
            "order",
            "is_hidden",
            "background_image",
            "background_color",
            "overlay_color",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        config = getattr(self.instance, "config", {}) or {}

        self.fields["config_title"].initial = config.get("title", "")
        self.fields["config_body"].initial = config.get("body", "")
        self.fields["config_cta_label"].initial = config.get("cta_label", "")
        self.fields["config_cta_url"].initial = config.get("cta_url", "")
        self.fields["config_image_url"].initial = config.get("image_url", "")
        self.fields["config_image_alt"].initial = config.get("image_alt", "")

        images = config.get("images") or []
        for idx in range(1, 7):
            image = images[idx - 1] if len(images) >= idx else {}
            self.fields[f"config_gallery_image_{idx}_url"].initial = image.get("url", "")
            self.fields[f"config_gallery_image_{idx}_alt"].initial = image.get("alt", "")

        items = config.get("items") or []
        for idx in range(1, 5):
            item = items[idx - 1] if len(items) >= idx else {}
            self.fields[f"config_faq_{idx}_question"].initial = item.get("question", "")
            self.fields[f"config_faq_{idx}_answer"].initial = item.get("answer", "")

        self.fields["config_custom_html"].initial = config.get("html", "")

        field_type_map = {
            "config_title": "hero,text,image,gallery,faq,custom",
            "config_body": "hero,text,image,gallery,faq",
            "config_cta_label": "hero,text",
            "config_cta_url": "hero,text",
            "config_image_url": "image",
            "config_image_alt": "image",
            "config_custom_html": "custom",
        }
        for idx in range(1, 7):
            field_type_map[f"config_gallery_image_{idx}_url"] = "gallery"
            field_type_map[f"config_gallery_image_{idx}_alt"] = "gallery"
        for idx in range(1, 5):
            field_type_map[f"config_faq_{idx}_question"] = "faq"
            field_type_map[f"config_faq_{idx}_answer"] = "faq"

        for name, types in field_type_map.items():
            field = self.fields.get(name)
            if field:
                field.widget.attrs["data-section-types"] = types

    def clean(self):
        cleaned_data = super().clean()
        section_type = cleaned_data.get("section_type")
        known_keys = {"title", "body", "cta_label", "cta_url", "image_url", "image_alt", "images", "items", "html"}
        config = {
            key: value
            for key, value in (self.instance.config or {}).items()
            if key not in known_keys
        }

        title = cleaned_data.get("config_title")
        body = cleaned_data.get("config_body")
        cta_label = cleaned_data.get("config_cta_label")
        cta_url = cleaned_data.get("config_cta_url")
        image_url = cleaned_data.get("config_image_url")
        image_alt = cleaned_data.get("config_image_alt")
        custom_html = cleaned_data.get("config_custom_html")

        if title:
            config["title"] = title
        if body and section_type in {"hero", "text", "image", "gallery", "faq"}:
            config["body"] = body
        if section_type in {"hero", "text"}:
            if cta_label:
                config["cta_label"] = cta_label
            if cta_url:
                config["cta_url"] = cta_url
        if section_type == "image":
            if image_url:
                config["image_url"] = image_url
            if image_alt:
                config["image_alt"] = image_alt
        if section_type == "gallery":
            images = []
            for idx in range(1, 7):
                url = cleaned_data.get(f"config_gallery_image_{idx}_url")
                alt = cleaned_data.get(f"config_gallery_image_{idx}_alt")
                if url:
                    images.append({"url": url, "alt": alt or ""})
            if images:
                config["images"] = images
        if section_type == "faq":
            items = []
            for idx in range(1, 5):
                question = cleaned_data.get(f"config_faq_{idx}_question")
                answer = cleaned_data.get(f"config_faq_{idx}_answer")
                if question or answer:
                    items.append({"question": question or "", "answer": answer or ""})
            if items:
                config["items"] = items
        if section_type == "custom" and custom_html:
            config["html"] = custom_html

        cleaned_data["config"] = config
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.config = self.cleaned_data.get("config", {})
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class PageSectionInline(GenericStackedInline):
    model = PageSection
    form = PageSectionAdminForm
    extra = 1
    fields = (
        "section_type",
        "order",
        "is_hidden",
        "background_image",
        "background_color",
        "overlay_color",
        "config_title",
        "config_body",
        "config_cta_label",
        "config_cta_url",
        "config_image_url",
        "config_image_alt",
        "config_gallery_image_1_url",
        "config_gallery_image_1_alt",
        "config_gallery_image_2_url",
        "config_gallery_image_2_alt",
        "config_gallery_image_3_url",
        "config_gallery_image_3_alt",
        "config_gallery_image_4_url",
        "config_gallery_image_4_alt",
        "config_gallery_image_5_url",
        "config_gallery_image_5_alt",
        "config_gallery_image_6_url",
        "config_gallery_image_6_alt",
        "config_faq_1_question",
        "config_faq_1_answer",
        "config_faq_2_question",
        "config_faq_2_answer",
        "config_faq_3_question",
        "config_faq_3_answer",
        "config_faq_4_question",
        "config_faq_4_answer",
        "config_custom_html",
    )
    ordering = ("order",)


PAGECOPY_FONT_PAGES = {
    HomePageCopy: PageFontSetting.Page.HOME,
    ServicesPageCopy: PageFontSetting.Page.SERVICES,
    StorePageCopy: PageFontSetting.Page.STORE,
    MerchPageCopy: PageFontSetting.Page.MERCH,
    AboutPageCopy: PageFontSetting.Page.ABOUT,
}


class PageCopyAdminMixin(admin.ModelAdmin):
    change_form_template = "admin/core/pagecopy/change_form.html"
    save_on_top = True
    inlines = [PageSectionInline]

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if isinstance(db_field, models.TextField):
            formfield.widget = CKEditorUploadingWidget(config_name="pagecopy")
        return formfield

    def _get_draft_data(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return {}
        content_type = ContentType.objects.get_for_model(obj.__class__)
        draft = PageCopyDraft.objects.filter(content_type=content_type, object_id=obj.pk).first()
        if not draft:
            return {}
        return draft.data or {}

    def get_urls(self):
        urls = super().get_urls()
        opts = self.model._meta
        custom = [
            path(
                "preview/",
                self.admin_site.admin_view(self.preview_view),
                name=f"{opts.app_label}_{opts.model_name}_preview",
            ),
        ]
        return custom + urls

    def _get_preview_instance(self, request, obj):
        if request.method != "POST":
            return obj
        form_class = self.get_form(request, obj=obj, change=True)
        form = form_class(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            return form.save(commit=False)
        return obj

    def preview_view(self, request):
        config = PREVIEW_CONFIG.get(self.model)
        if not config:
            return HttpResponse("Preview is not configured for this page.", status=400)

        object_id = request.GET.get("object_id") or request.POST.get("object_id")
        obj = None
        if object_id:
            obj = self.get_object(request, object_id)
        if not obj:
            try:
                obj = self.model.objects.first()
            except Exception:
                obj = None
        if not obj:
            return HttpResponse("Preview data not available.", status=400)

        preview_instance = self._get_preview_instance(request, obj)
        if request.method != "POST":
            draft = PageCopyDraft.for_instance(obj)
            if draft:
                draft.apply_to_instance(preview_instance)
        text_fields = [
            field.name
            for field in self.model._meta.get_fields()
            if isinstance(field, (models.CharField, models.TextField))
        ]
        preview_copy = PreviewCopy(preview_instance, text_fields)
        base_href = request.build_absolute_uri("/")
        html_text = render_pagecopy_preview(request, self.model, preview_copy, base_href)
        if not html_text:
            return HttpResponse("Preview is not available for this page.", status=400)
        return HttpResponse(html_text)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        opts = self.model._meta
        try:
            preview_url = reverse(f"admin:{opts.app_label}_{opts.model_name}_preview")
            if object_id:
                preview_url = f"{preview_url}?object_id={object_id}"
        except Exception:
            preview_url = None
        obj = None
        if object_id:
            obj = self.get_object(request, object_id)
        if not obj:
            try:
                obj = self.model.objects.first()
            except Exception:
                obj = None
        extra_context["pagecopy_preview_url"] = preview_url
        extra_context["pagecopy_draft_data"] = self._get_draft_data(obj)
        extra_context["pagecopy_meta"] = {
            "model": f"{opts.app_label}.{opts.model_name}",
            "object_id": getattr(obj, "pk", None),
        }
        extra_context["pagecopy_text_fields"] = [
            {
                "name": field.name,
                "type": "rich" if isinstance(field, models.TextField) else "plain",
            }
            for field in self.model._meta.get_fields()
            if isinstance(field, (models.CharField, models.TextField)) and getattr(field, "editable", True)
        ]
        try:
            extra_context["page_section_layout_save_url"] = reverse("admin-pagecopy-save-section-layout")
            extra_context["page_section_order_save_url"] = reverse("admin-pagecopy-save-section-order")
        except Exception:
            extra_context["page_section_layout_save_url"] = None
            extra_context["page_section_order_save_url"] = None
        font_page = PAGECOPY_FONT_PAGES.get(self.model)
        if font_page:
            extra_context["page_font_page"] = font_page
            extra_context["page_font_options"] = FontPreset.objects.filter(is_active=True).order_by("name")
            extra_context["page_font_setting"] = PageFontSetting.objects.filter(page=font_page).first()
            extra_context["page_font_styles"] = (
                extra_context["page_font_setting"].style_overrides
                if extra_context["page_font_setting"]
                else {}
            )
            try:
                extra_context["page_font_save_url"] = reverse("admin-pagecopy-save-fonts")
                extra_context["page_font_upload_url"] = reverse("admin-pagecopy-upload-font")
                extra_context["page_font_style_save_url"] = reverse("admin-pagecopy-save-font-styles")
            except Exception:
                extra_context["page_font_save_url"] = None
                extra_context["page_font_upload_url"] = None
                extra_context["page_font_style_save_url"] = None
        try:
            extra_context["pagecopy_save_draft_url"] = reverse("admin-pagecopy-save-draft")
        except Exception:
            extra_context["pagecopy_save_draft_url"] = None
        return super().changeform_view(
            request,
            object_id=object_id,
            form_url=form_url,
            extra_context=extra_context,
        )

    def save_model(self, request, obj, form, change):
        content_type = None
        draft = None
        if change and getattr(obj, "pk", None):
            content_type = ContentType.objects.get_for_model(obj.__class__)
            draft = PageCopyDraft.objects.filter(content_type=content_type, object_id=obj.pk).first()
            if draft and draft.data:
                changed = set(getattr(form, "changed_data", []) or [])
                for field_name, value in (draft.data or {}).items():
                    if field_name in changed:
                        continue
                    try:
                        field_obj = obj._meta.get_field(field_name)
                    except Exception:
                        continue
                    if isinstance(field_obj, (models.CharField, models.TextField)):
                        setattr(obj, field_name, value)
        super().save_model(request, obj, form, change)
        if content_type and getattr(obj, "pk", None):
            PageCopyDraft.objects.filter(content_type=content_type, object_id=obj.pk).delete()


HOME_HERO_CAROUSEL_SLOTS = (
    ("hero_carousel_1", HeroImage.Location.HOME_CAROUSEL_A, "Slide 1"),
    ("hero_carousel_2", HeroImage.Location.HOME_CAROUSEL_B, "Slide 2"),
    ("hero_carousel_3", HeroImage.Location.HOME_CAROUSEL_C, "Slide 3"),
    ("hero_carousel_4", HeroImage.Location.HOME_CAROUSEL_D, "Slide 4"),
)


class HomePageCopyAdminForm(forms.ModelForm):
    hero_main_image = forms.ImageField(
        required=False,
        label="Hero background image",
        help_text="Default hero image (used when no carousel slides are set).",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*"}),
    )
    hero_main_alt_text = forms.CharField(
        required=False,
        label="Hero background alt text",
        max_length=160,
    )
    hero_main_caption = forms.CharField(
        required=False,
        label="Hero background caption",
        max_length=160,
    )
    hero_carousel_1_image = forms.ImageField(
        required=False,
        label="Carousel slide 1 image",
        help_text="Optional. Upload a 16:9 image. If any slide is set, the hero switches to a carousel.",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*"}),
    )
    hero_carousel_1_alt_text = forms.CharField(
        required=False,
        label="Carousel slide 1 alt text",
        max_length=160,
    )
    hero_carousel_1_caption = forms.CharField(
        required=False,
        label="Carousel slide 1 caption",
        max_length=160,
    )
    hero_carousel_2_image = forms.ImageField(
        required=False,
        label="Carousel slide 2 image",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*"}),
    )
    hero_carousel_2_alt_text = forms.CharField(
        required=False,
        label="Carousel slide 2 alt text",
        max_length=160,
    )
    hero_carousel_2_caption = forms.CharField(
        required=False,
        label="Carousel slide 2 caption",
        max_length=160,
    )
    hero_carousel_3_image = forms.ImageField(
        required=False,
        label="Carousel slide 3 image",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*"}),
    )
    hero_carousel_3_alt_text = forms.CharField(
        required=False,
        label="Carousel slide 3 alt text",
        max_length=160,
    )
    hero_carousel_3_caption = forms.CharField(
        required=False,
        label="Carousel slide 3 caption",
        max_length=160,
    )
    hero_carousel_4_image = forms.ImageField(
        required=False,
        label="Carousel slide 4 image",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*"}),
    )
    hero_carousel_4_alt_text = forms.CharField(
        required=False,
        label="Carousel slide 4 alt text",
        max_length=160,
    )
    hero_carousel_4_caption = forms.CharField(
        required=False,
        label="Carousel slide 4 caption",
        max_length=160,
    )

    class Meta:
        model = HomePageCopy
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "layout_overrides" in self.fields:
            self.fields["layout_overrides"].required = False
            self.fields["layout_overrides"].widget = forms.HiddenInput()
        locations = [slot[1] for slot in HOME_HERO_CAROUSEL_SLOTS]
        try:
            assets = HeroImage.objects.filter(location__in=locations)
        except Exception:
            assets = []
        asset_map = {asset.location: asset for asset in assets}

        try:
            hero_asset = HeroImage.objects.filter(location=HeroImage.Location.HOME).first()
        except Exception:
            hero_asset = None
        if hero_asset and getattr(hero_asset, "image", None):
            self.fields["hero_main_image"].initial = hero_asset.image
        if hero_asset:
            self.fields["hero_main_alt_text"].initial = hero_asset.alt_text
            self.fields["hero_main_caption"].initial = hero_asset.caption

        for prefix, location, label in HOME_HERO_CAROUSEL_SLOTS:
            asset = asset_map.get(location)
            image_field = f"{prefix}_image"
            alt_field = f"{prefix}_alt_text"
            caption_field = f"{prefix}_caption"
            if asset and getattr(asset, "image", None):
                self.fields[image_field].initial = asset.image
            if asset:
                self.fields[alt_field].initial = asset.alt_text
                self.fields[caption_field].initial = asset.caption

    def save_hero_asset(self):
        image_value = self.cleaned_data.get("hero_main_image")
        alt_text = (self.cleaned_data.get("hero_main_alt_text") or "").strip()
        caption = (self.cleaned_data.get("hero_main_caption") or "").strip()

        has_new_image = image_value not in (None, False)
        has_any_value = has_new_image or alt_text or caption
        asset = HeroImage.objects.filter(location=HeroImage.Location.HOME).first()
        if not asset and not has_any_value:
            return
        if not asset:
            asset = HeroImage(location=HeroImage.Location.HOME)

        if image_value is False:
            asset.image = None
        elif image_value:
            asset.image = image_value

        asset.alt_text = alt_text
        asset.caption = caption
        if not asset.title:
            asset.title = "Home hero"
        asset.is_active = bool(asset.image)
        asset.save()

    def save_carousel_assets(self):
        locations = [slot[1] for slot in HOME_HERO_CAROUSEL_SLOTS]
        existing_assets = {asset.location: asset for asset in HeroImage.objects.filter(location__in=locations)}

        for prefix, location, label in HOME_HERO_CAROUSEL_SLOTS:
            image_field = f"{prefix}_image"
            alt_field = f"{prefix}_alt_text"
            caption_field = f"{prefix}_caption"
            image_value = self.cleaned_data.get(image_field)
            alt_text = (self.cleaned_data.get(alt_field) or "").strip()
            caption = (self.cleaned_data.get(caption_field) or "").strip()

            asset = existing_assets.get(location)
            has_new_image = image_value not in (None, False)
            has_any_value = has_new_image or alt_text or caption

            if not asset and not has_any_value:
                continue

            if not asset:
                asset = HeroImage(location=location)

            if image_value is False:
                asset.image = None
            elif image_value:
                asset.image = image_value

            asset.alt_text = alt_text
            asset.caption = caption
            if not asset.title:
                asset.title = f"Home hero carousel {label}"
            asset.is_active = bool(asset.image)
            asset.save()


class HomePageFAQItemInline(admin.StackedInline):
    model = HomePageFAQItem
    extra = 1
    fields = ("order", "is_published", "question", "answer")
    ordering = ("order", "id")
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 3})},
    }


@admin.register(HomePageCopy)
class HomePageCopyAdmin(PageCopyAdminMixin, admin.ModelAdmin):
    list_display = ("label", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    inlines = [PageSectionInline, HomePageFAQItemInline]
    form = HomePageCopyAdminForm
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 3})},
    }
    fieldsets = (
        ("Meta", {"fields": ("meta_title", "meta_description", "default_background")}),
        ("Header & navigation", {
            "fields": (
                "skip_to_main_label",
                "brand_word_white",
                "brand_word_red",
                "brand_tagline",
                "nav_toggle_label",
                "nav_services_label",
                "nav_client_portal_label",
                "nav_login_label",
                "nav_products_label",
                "nav_merch_label",
                "nav_merch_badge",
                "nav_dealers_label",
                "nav_financing_label",
                "nav_about_label",
            )
        }),
        ("Hero", {
            "fields": (
                "hero_logo",
                "hero_logo_backdrop",
                "hero_logo_layout",
                "hero_logo_bg_style",
                "hero_logo_size",
                "hero_logo_show_ring",
                "hero_logo_photo_width",
                "hero_logo_photo_height",
                "hero_media_width",
                "hero_media_height",
                "hero_logo_alt",
                "hero_kicker",
                "hero_title",
                "hero_lead",
                "hero_primary_cta_label",
                "hero_secondary_cta_label",
                "hero_background_asset",
            )
        }),
        ("Hero background", {
            "fields": (
                "hero_main_image",
                "hero_main_alt_text",
                "hero_main_caption",
            ),
            "description": "Default hero image used when the carousel is empty. If any carousel slide is set, it overrides this background.",
        }),
        ("Layout overrides", {
            "fields": ("layout_overrides",),
            "description": "Hidden layout data for the page builder.",
            "classes": ("layout-overrides",),
        }),
        ("Hero carousel", {
            "fields": (
                "hero_carousel_1_image",
                "hero_carousel_1_alt_text",
                "hero_carousel_1_caption",
                "hero_carousel_2_image",
                "hero_carousel_2_alt_text",
                "hero_carousel_2_caption",
                "hero_carousel_3_image",
                "hero_carousel_3_alt_text",
                "hero_carousel_3_caption",
                "hero_carousel_4_image",
                "hero_carousel_4_alt_text",
                "hero_carousel_4_caption",
            ),
            "description": "Upload up to 4 slides. If any slide is set, the hero image switches to a carousel.",
        }),
        ("Hero stats", {
            "fields": (
                "hero_stat_1_title",
                "hero_stat_1_subtitle",
                "hero_stat_2_title",
                "hero_stat_2_subtitle",
                "hero_stat_3_title",
                "hero_stat_3_subtitle",
            )
        }),
        ("Hero quick actions (mobile)", {
            "fields": (
                "hero_mobile_action_1_title",
                "hero_mobile_action_1_subtitle",
                "hero_mobile_action_2_title",
                "hero_mobile_action_2_subtitle",
                "hero_mobile_action_3_title",
                "hero_mobile_action_3_subtitle",
                "hero_mobile_action_4_title",
                "hero_mobile_action_4_subtitle",
            )
        }),
        ("Services", {
            "fields": (
                "services_title",
                "services_desc",
                "services_cta_label",
                "services_mobile_kicker",
                "services_mobile_action_1_title",
                "services_mobile_action_1_subtitle",
                "services_mobile_action_2_title",
                "services_mobile_action_2_subtitle",
                "services_mobile_action_3_title",
                "services_mobile_action_3_subtitle",
                "services_mobile_action_4_title",
                "services_mobile_action_4_subtitle",
            )
        }),
        ("Services search & labels", {
            "fields": (
                "services_search_placeholder",
                "services_filter_all_categories_label",
                "services_search_button_label",
                "services_reset_filters_label",
                "services_live_results_label",
                "services_results_label",
                "services_featured_label",
                "services_no_results_label",
                "services_empty_label",
                "services_duration_prefix",
                "services_duration_suffix",
                "services_book_now_label",
                "services_nothing_found_label",
                "services_failed_load_label",
            )
        }),
        ("Photo gallery", {
            "fields": (
                "gallery_title",
                "gallery_desc",
                "gallery_cta_label",
                "gallery_cta_url",
            )
        }),
        ("Shared pricing labels", {
            "fields": (
                "contact_for_estimate_label",
                "from_label",
            )
        }),
        ("Products", {
            "fields": (
                "products_title",
                "products_desc",
                "products_cta_label",
                "products_mobile_kicker",
                "products_mobile_action_1_title",
                "products_mobile_action_1_subtitle",
                "products_mobile_action_2_title",
                "products_mobile_action_2_subtitle",
            )
        }),
        ("Products labels", {
            "fields": (
                "products_dealer_label",
                "products_save_label",
                "products_contact_us_label",
                "products_view_label",
                "products_select_options_label",
                "products_add_to_cart_label",
                "products_empty_label",
                "products_empty_cta_label",
            )
        }),
        ("How we work", {
            "fields": (
                "how_title",
                "how_desc",
                "how_step_1_title",
                "how_step_1_desc",
                "how_step_2_title",
                "how_step_2_desc",
                "how_step_3_title",
                "how_step_3_desc",
                "how_step_4_title",
                "how_step_4_desc",
            )
        }),
        ("Why BGM", {
            "fields": (
                "why_title",
                "why_desc",
                "why_tile_1_title",
                "why_tile_1_desc",
                "why_tile_2_title",
                "why_tile_2_desc",
                "why_tile_3_title",
                "why_tile_3_desc",
                "why_warranty_title",
                "why_warranty_desc",
                "why_warranty_cta",
                "why_warranty_aria_label",
                "why_warranty_title_attr",
            )
        }),
        ("FAQ", {
            "fields": (
                "faq_title",
                "faq_desc",
            ),
            "description": "FAQ entries are managed below in “Home page FAQs”. Unpublished items are saved as drafts and won’t display on the site.",
        }),
        ("Final CTA", {
            "fields": (
                "final_cta_title",
                "final_cta_desc",
                "final_cta_primary_label",
                "final_cta_secondary_auth_label",
                "final_cta_secondary_guest_label",
            )
        }),
        ("Contact modal", {
            "fields": (
                "contact_fab_label",
                "contact_modal_title",
                "contact_email_label",
                "contact_phone_label",
                "contact_copy_label",
                "contact_copy_success_label",
                "contact_copy_failed_label",
                "contact_call_label",
                "contact_write_email_label",
                "contact_text_label",
            )
        }),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        if HomePageCopy.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Page")
    def label(self, obj):
        return "Home page"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if hasattr(form, "save_hero_asset"):
            form.save_hero_asset()
        if hasattr(form, "save_carousel_assets"):
            form.save_carousel_assets()


@admin.register(ServicesPageCopy)
class ServicesPageCopyAdmin(PageCopyAdminMixin, admin.ModelAdmin):
    list_display = ("label", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 3})},
    }
    fieldsets = (
        ("Meta", {"fields": ("meta_title", "meta_description", "default_background")}),
        ("Header & navigation", {
            "fields": (
                "skip_to_main_label",
                "brand_word_white",
                "brand_word_red",
                "brand_tagline",
                "nav_toggle_label",
                "nav_services_label",
                "nav_client_portal_label",
                "nav_login_label",
                "nav_products_label",
                "nav_merch_label",
                "nav_merch_badge",
                "nav_dealers_label",
                "nav_financing_label",
                "nav_about_label",
            )
        }),
        ("Hero", {"fields": ("hero_title", "hero_lead", "hero_cta_label")}),
        ("Catalog & filters", {
            "fields": (
                "section_title",
                "search_placeholder",
                "filter_all_categories_label",
                "search_button_label",
                "reset_button_label",
                "search_results_label",
                "live_no_results_label",
                "live_error_label",
                "search_no_results_prefix",
                "search_no_results_suffix",
                "category_empty_label",
                "uncategorized_title",
                "catalog_empty_label",
            )
        }),
        ("Service cards", {
            "fields": (
                "service_image_aria_label",
                "service_image_fallback_label",
                "book_aria_prefix",
                "pick_time_label",
                "contact_for_estimate_label",
                "from_label",
                "duration_separator",
                "duration_unit",
            )
        }),
        ("Booking modal — labels", {
            "fields": (
                "booking_modal_title_prefix",
                "booking_close_label",
                "booking_staff_label",
                "booking_staff_picker_label",
                "booking_choose_time_label",
                "booking_prev_label",
                "booking_today_label",
                "booking_next_label",
                "booking_mobile_day_label",
                "booking_mobile_pick_day_label",
                "booking_jump_today_label",
                "booking_available_times_label",
                "booking_no_open_times_label",
                "booking_no_open_times_on_prefix",
                "booking_no_open_times_on_suffix",
                "booking_no_availability_label",
                "booking_scroll_hint_desktop",
                "booking_scroll_hint_mobile",
                "booking_summary_label",
                "booking_summary_default",
                "booking_summary_staff_prefix",
                "booking_summary_time_prefix",
                "booking_summary_time_selected_label",
                "booking_full_name_label",
                "booking_full_name_placeholder",
                "booking_email_label",
                "booking_email_placeholder",
                "booking_phone_label",
                "booking_phone_placeholder",
                "booking_phone_title",
                "booking_confirmation_hint",
                "booking_cancel_label",
                "booking_confirm_label",
            )
        }),
        ("Booking modal — messages", {
            "fields": (
                "booking_no_staff_label",
                "booking_availability_error_label",
                "booking_failed_slots_label",
                "booking_missing_contact_error",
                "booking_create_error_label",
                "booking_created_label",
                "booking_time_label",
                "booking_error_label",
            )
        }),
        ("Contact modal", {
            "fields": (
                "contact_fab_label",
                "contact_modal_title",
                "contact_close_label",
                "contact_email_label",
                "contact_phone_label",
                "contact_copy_label",
                "contact_copy_success_label",
                "contact_copy_failed_label",
                "contact_call_label",
                "contact_write_email_label",
                "contact_text_label",
            )
        }),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        if ServicesPageCopy.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Page")
    def label(self, obj):
        return "Services page"


@admin.register(StorePageCopy)
class StorePageCopyAdmin(PageCopyAdminMixin, admin.ModelAdmin):
    list_display = ("label", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 3})},
    }
    fieldsets = (
        ("Meta", {"fields": ("page_title", "meta_title", "meta_description", "default_background")}),
        ("Header & navigation", {
            "fields": (
                "brand_word_white",
                "brand_word_red",
                "brand_tagline",
                "nav_toggle_label",
                "nav_services_label",
                "nav_client_portal_label",
                "nav_login_label",
                "nav_products_label",
                "nav_merch_label",
                "nav_merch_badge",
                "nav_dealers_label",
                "nav_financing_label",
                "nav_about_label",
            )
        }),
        ("Hero", {
            "fields": (
                "hero_title",
                "hero_lead",
                "hero_primary_cta_label",
                "hero_secondary_cta_label",
                "hero_disclaimer_fallback",
            )
        }),
        ("Filters", {
            "fields": (
                "filters_toggle_label",
                "filters_active_badge",
                "filters_reset_label",
                "filters_heading",
                "filters_close_label",
                "filters_category_label",
                "filters_make_label",
                "filters_model_label",
                "filters_year_label",
                "filters_apply_label",
                "filters_clear_label",
            )
        }),
        ("Categories", {
            "fields": (
                "categories_title",
                "categories_desc",
                "categories_empty_label",
            )
        }),
        ("Results", {
            "fields": (
                "results_title",
                "results_desc",
                "results_empty_label",
            )
        }),
        ("New arrivals", {
            "fields": (
                "new_arrivals_title",
                "new_arrivals_cart_label",
            )
        }),
        ("Browse by category", {
            "fields": (
                "browse_title",
                "browse_desc",
                "browse_view_all_label",
            )
        }),
        ("Product comparison", {
            "fields": (
                "comparison_title",
                "comparison_desc",
                "comparison_left_title",
                "comparison_left_subtitle",
                "comparison_left_body",
                "comparison_right_title",
                "comparison_right_subtitle",
                "comparison_right_body",
            )
        }),
        ("Pricing labels", {
            "fields": (
                "contact_for_estimate_label",
                "from_label",
                "dealer_label",
                "save_label",
            )
        }),
        ("Contact modal", {
            "fields": (
                "contact_fab_label",
                "contact_modal_title",
                "contact_close_label",
                "contact_email_label",
                "contact_phone_label",
                "contact_copy_label",
                "contact_copy_success_label",
                "contact_copy_failed_label",
                "contact_call_label",
                "contact_write_email_label",
                "contact_text_label",
            )
        }),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        if StorePageCopy.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Page")
    def label(self, obj):
        return "Store page"


@admin.register(ClientPortalPageCopy)
class ClientPortalPageCopyAdmin(PageCopyAdminMixin, admin.ModelAdmin):
    list_display = ("label", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 3})},
    }
    fieldsets = (
        ("Meta", {"fields": ("page_title", "meta_title", "meta_description")}),
        ("Brand & navigation", {
            "fields": (
                "brand_mark",
                "brand_name",
                "mobile_menu_label",
                "mobile_controls_aria_label",
                "sidebar_close_label",
                "nav_overview_label",
                "nav_appointments_label",
                "nav_orders_label",
                "nav_files_label",
                "nav_notifications_label",
                "nav_profile_label",
                "nav_back_home_label",
                "nav_sign_out_label",
            )
        }),
        ("Dashboard overview", {
            "fields": (
                "welcome_back_prefix",
                "welcome_back_suffix",
                "dashboard_kicker",
                "upcoming_title",
                "upcoming_empty_label",
                "action_cancel_label",
                "action_reschedule_label",
                "stats_title",
                "stats_chart_label",
                "recent_title",
                "recent_empty_label",
                "table_date_label",
                "table_service_label",
                "table_staff_label",
                "table_status_label",
                "table_amount_label",
            )
        }),
	        ("Rates & facts", {
	            "fields": (
	                "rates_title",
	                "rates_shop_label",
	                "rates_shop_value",
	                "rates_cad_label",
	                "rates_cad_value",
	                "rates_customer_parts_label",
	                "rates_customer_parts_value",
	                "quick_facts_title",
	                "quick_fact_1",
	                "quick_fact_2",
	                "quick_fact_3",
	            )
	        }),
        ("Policies & care", {
            "fields": (
                "policies_title",
                "policy_item_1",
                "policy_item_2",
                "policy_item_3",
                "policy_item_4",
                "care_title",
                "care_item_1",
                "care_item_2",
                "care_item_3",
            )
        }),
        ("Appointments & orders tabs", {
            "fields": (
                "appointments_title",
                "appointments_book_label",
                "appointments_completed_label",
                "appointments_empty_label",
                "orders_title",
                "orders_go_to_products_label",
                "orders_empty_label",
            )
        }),
        ("Files tab", {
            "fields": (
                "files_title",
                "files_lead",
                "files_max_size_label",
                "files_description_label",
                "files_description_placeholder",
                "files_dropzone_title",
                "files_accepted_prefix",
                "files_accepted_suffix",
                "files_choose_label",
                "files_your_files_title",
                "files_total_suffix",
                "files_empty_label",
                "files_remove_label",
                "files_file_fallback_label",
            )
        }),
        ("Notifications & profile", {
            "fields": (
                "notifications_title",
                "notifications_empty_label",
                "profile_title",
                "profile_first_name_label",
                "profile_last_name_label",
                "profile_phone_label",
                "profile_email_label",
                "profile_birth_date_label",
                "profile_save_label",
                "profile_email_prefs_title",
                "profile_email_marketing_label",
                "profile_email_product_label",
                "profile_email_service_label",
            )
        }),
        ("Reschedule modal", {
            "fields": (
                "reschedule_modal_title",
                "reschedule_close_label",
                "reschedule_staff_label",
                "reschedule_choose_time_label",
                "reschedule_prev_label",
                "reschedule_today_label",
                "reschedule_next_label",
                "reschedule_shift_scroll_hint",
                "reschedule_cancel_label",
                "reschedule_save_label",
                "reschedule_no_techs_label",
                "reschedule_no_availability_label",
            )
        }),
        ("Alerts & status messages", {
            "fields": (
                "cancel_confirm_message",
                "cancel_error_prefix",
                "reschedule_fetch_error_label",
                "reschedule_failed_slots_label",
                "reschedule_success_prefix",
                "reschedule_failed_label",
                "files_removing_label",
                "files_removed_label",
                "files_delete_error_label",
                "files_delete_failed_label",
                "files_uploading_label",
                "files_upload_success_label",
                "files_upload_failed_label",
                "files_too_large_prefix",
                "files_too_large_suffix",
            )
        }),
        ("Contact modal", {
            "fields": (
                "contact_fab_label",
                "contact_modal_title",
                "contact_close_label",
                "contact_email_label",
                "contact_phone_label",
                "contact_copy_label",
                "contact_copy_success_label",
                "contact_copy_failed_label",
                "contact_call_label",
                "contact_write_email_label",
                "contact_text_label",
            )
        }),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        if ClientPortalPageCopy.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Page")
    def label(self, obj):
        return "Client portal"


class MerchPageCopyAdminForm(forms.ModelForm):
    hero_image = forms.ImageField(
        required=False,
        label="Hero image",
        help_text="Upload a 16:9 hero image (webp/jpg recommended).",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*"}),
    )
    hero_image_alt_text = forms.CharField(
        required=False,
        label="Hero image alt text",
        max_length=160,
    )
    hero_image_caption = forms.CharField(
        required=False,
        label="Hero image caption",
        max_length=160,
    )

    class Meta:
        model = MerchPageCopy
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            asset = HeroImage.objects.filter(location=HeroImage.Location.MERCH).first()
        except Exception:
            asset = None
        if asset and getattr(asset, "image", None):
            self.fields["hero_image"].initial = asset.image
        if asset:
            self.fields["hero_image_alt_text"].initial = asset.alt_text
            self.fields["hero_image_caption"].initial = asset.caption

    def save_hero_asset(self):
        image_value = self.cleaned_data.get("hero_image")
        alt_text = (self.cleaned_data.get("hero_image_alt_text") or "").strip()
        caption = (self.cleaned_data.get("hero_image_caption") or "").strip()

        has_new_image = image_value not in (None, False)
        has_any_value = has_new_image or alt_text or caption
        asset = HeroImage.objects.filter(location=HeroImage.Location.MERCH).first()
        if not asset and not has_any_value:
            return
        if not asset:
            asset = HeroImage(location=HeroImage.Location.MERCH)

        if image_value is False:
            asset.image = None
        elif image_value:
            asset.image = image_value

        asset.alt_text = alt_text
        asset.caption = caption
        if not asset.title:
            asset.title = "Merch hero"
        asset.is_active = bool(asset.image)
        asset.save()


@admin.register(MerchPageCopy)
class MerchPageCopyAdmin(PageCopyAdminMixin, admin.ModelAdmin):
    list_display = ("label", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    form = MerchPageCopyAdminForm
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 3})},
    }
    fieldsets = (
        ("Meta", {"fields": ("page_title", "meta_title", "meta_description")}),
        ("Header & navigation", {
            "fields": (
                "skip_to_main_label",
                "brand_word_white",
                "brand_word_red",
                "brand_tagline",
                "nav_toggle_label",
                "nav_services_label",
                "nav_client_portal_label",
                "nav_login_label",
                "nav_products_label",
                "nav_merch_label",
                "nav_merch_badge",
                "nav_dealers_label",
                "nav_financing_label",
                "nav_about_label",
            )
        }),
        ("Hero", {
            "fields": (
                "hero_kicker",
                "hero_title",
                "hero_lead",
                "hero_primary_cta_label",
                "hero_secondary_cta_label",
                "hero_disclaimer_fallback",
            )
        }),
        ("Hero image", {
            "fields": (
                "hero_image",
                "hero_image_alt_text",
                "hero_image_caption",
            ),
            "description": "Controls the merch hero image displayed above the intro copy.",
        }),
        ("First drop section", {
            "fields": (
                "section_title",
                "section_desc",
                "section_badge_label",
            )
        }),
        ("Coming soon state", {
            "fields": (
                "coming_soon_enabled",
                "coming_soon_badge",
                "coming_soon_title",
                "coming_soon_desc",
            )
        }),
        ("Card meta labels", {"fields": ("card_colors_label", "card_sizes_label")}),
        ("Drop idea cards", {
            "fields": (
                "card_1_title",
                "card_1_desc",
                "card_1_photo",
                "card_1_photo_alt",
                "card_1_colors",
                "card_1_sizes",
                "card_2_title",
                "card_2_desc",
                "card_2_photo",
                "card_2_photo_alt",
                "card_2_colors",
                "card_2_sizes",
                "card_3_title",
                "card_3_desc",
                "card_3_photo",
                "card_3_photo_alt",
                "card_3_colors",
                "card_3_sizes",
                "card_4_title",
                "card_4_desc",
                "card_4_photo",
                "card_4_photo_alt",
                "card_4_colors",
                "card_4_sizes",
            )
        }),
        ("Social links", {
            "fields": (
                "social_section_title",
                "social_section_desc",
                "social_link_1_label",
                "social_link_1_url",
                "social_link_2_label",
                "social_link_2_url",
                "social_link_3_label",
                "social_link_3_url",
                "social_link_4_label",
                "social_link_4_url",
            )
        }),
        ("Bottom CTA", {"fields": ("bottom_cta_label",)}),
        ("Contact modal", {
            "fields": (
                "contact_email",
                "contact_email_subject",
                "contact_phone",
                "contact_phone_display",
                "contact_fab_label",
                "contact_modal_title",
                "contact_close_label",
                "contact_email_label",
                "contact_phone_label",
                "contact_copy_label",
                "contact_copy_success_label",
                "contact_copy_failed_label",
                "contact_call_label",
                "contact_write_email_label",
                "contact_text_label",
            )
        }),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        if MerchPageCopy.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Page")
    def label(self, obj):
        return "Merch page"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if hasattr(form, "save_hero_asset"):
            form.save_hero_asset()


@admin.register(FinancingPageCopy)
class FinancingPageCopyAdmin(PageCopyAdminMixin, admin.ModelAdmin):
    list_display = ("label", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 3})},
    }
    fieldsets = (
        ("Meta", {"fields": ("meta_title", "meta_description")}),
        ("Header & navigation", {
            "fields": (
                "skip_to_main_label",
                "brand_word_white",
                "brand_word_red",
                "brand_tagline",
                "nav_toggle_label",
                "nav_services_label",
                "nav_client_portal_label",
                "nav_login_label",
                "nav_products_label",
                "nav_merch_label",
                "nav_merch_badge",
                "nav_dealers_label",
                "nav_financing_label",
                "nav_about_label",
            )
        }),
        ("Hero", {
            "fields": (
                "hero_kicker",
                "hero_title",
                "hero_lead",
                "hero_primary_cta_label",
                "hero_secondary_cta_label",
                "hero_image_alt",
                "hero_disclaimer",
            )
        }),
        ("Providers section", {
            "fields": (
                "providers_title",
                "providers_desc",
                "providers_badge_label",
            )
        }),
        ("Provider — Canadian Financial", {
            "fields": (
                "provider_1_title",
                "provider_1_meta",
                "provider_1_desc",
                "provider_1_primary_cta_label",
                "provider_1_secondary_cta_label",
            )
        }),
        ("Provider — Afterpay", {
            "fields": (
                "provider_2_title",
                "provider_2_meta_prefix",
                "provider_2_meta_amount",
                "provider_2_desc",
                "provider_2_primary_cta_label",
                "provider_2_secondary_cta_label",
            )
        }),
        ("Providers CTA row", {
            "fields": (
                "providers_bottom_primary_cta_label",
                "providers_bottom_secondary_cta_label",
            )
        }),
        ("Steps", {
            "fields": (
                "steps_title",
                "steps_desc",
                "step_1_title",
                "step_1_desc",
                "step_2_title",
                "step_2_desc",
                "step_3_title",
                "step_3_desc",
                "step_4_title",
                "step_4_desc",
            )
        }),
        ("FAQ", {
            "fields": (
                "faq_title",
                "faq_desc",
                "faq_1_title",
                "faq_1_desc",
                "faq_2_title",
                "faq_2_desc",
                "faq_3_title",
                "faq_3_desc_prefix",
                "faq_3_desc_amount",
                "faq_3_desc_suffix",
                "faq_4_title",
                "faq_4_desc",
                "faq_4_cta_label",
            )
        }),
        ("Contact modal", {
            "fields": (
                "contact_fab_label",
                "contact_modal_title",
                "contact_close_label",
                "contact_email_label",
                "contact_phone_label",
                "contact_copy_label",
                "contact_copy_success_label",
                "contact_copy_failed_label",
                "contact_call_label",
                "contact_write_email_label",
                "contact_text_label",
            )
        }),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        if FinancingPageCopy.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Page")
    def label(self, obj):
        return "Financing page"


@admin.register(AboutPageCopy)
class AboutPageCopyAdmin(PageCopyAdminMixin, admin.ModelAdmin):
    list_display = ("label", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 3})},
    }
    fieldsets = (
        ("Meta", {"fields": ("meta_title", "meta_description")}),
        ("Header & navigation", {
            "fields": (
                "skip_to_main_label",
                "brand_word_white",
                "brand_word_red",
                "brand_tagline",
                "nav_toggle_label",
                "nav_services_label",
                "nav_client_portal_label",
                "nav_login_label",
                "nav_products_label",
                "nav_merch_label",
                "nav_merch_badge",
                "nav_dealers_label",
                "nav_financing_label",
                "nav_about_label",
            )
        }),
        ("Hero", {
            "fields": (
                "hero_title",
                "hero_lead",
                "hero_chip_1",
                "hero_chip_2",
                "hero_chip_3",
                "hero_image_alt",
                "hero_disclaimer",
            )
        }),
        ("Our story", {
            "fields": (
                "story_title",
                "story_paragraph_1",
                "story_paragraph_2",
                "story_photo",
                "story_photo_alt",
                "story_photo_placeholder",
                "story_photo_title",
                "story_photo_subtitle",
                "story_photo_caption",
            )
        }),
        ("What we build", {
            "fields": (
                "build_title",
                "build_item_1",
                "build_item_2",
                "build_item_3",
                "build_item_4",
                "build_item_5",
                "build_item_6",
                "build_item_7",
                "build_item_8",
            )
        }),
        ("How we work", {
            "fields": (
                "how_title",
                "how_step_1_title",
                "how_step_1_desc",
                "how_step_2_title",
                "how_step_2_desc",
                "how_step_3_title",
                "how_step_3_desc",
                "how_step_4_title",
                "how_step_4_desc",
            )
        }),
	        ("Rates & policies", {
	            "fields": (
	                "rates_title",
	                "rates_shop_label",
	                "rates_shop_value",
	                "rates_cad_label",
	                "rates_cad_value",
	                "rates_customer_parts_label",
	                "rates_customer_parts_value",
	                "rates_policies",
	            )
	        }),
        ("Location", {
            "fields": (
                "location_title",
                "location_address",
                "location_note",
                "location_primary_cta_label",
                "location_secondary_cta_label",
            )
        }),
        ("AMVIC", {
            "fields": (
                "amvic_title",
                "amvic_description",
            )
        }),
        ("Contact modal", {
            "fields": (
                "contact_fab_label",
                "contact_modal_title",
                "contact_close_label",
                "contact_email_label",
                "contact_phone_label",
                "contact_copy_label",
                "contact_copy_success_label",
                "contact_copy_failed_label",
                "contact_call_label",
                "contact_write_email_label",
                "contact_text_label",
            )
        }),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "rates_policies":
            kwargs["widget"] = forms.Textarea(attrs={"rows": 5})
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def has_add_permission(self, request):
        if AboutPageCopy.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Page")
    def label(self, obj):
        return "About page"


@admin.register(DealerStatusPageCopy)
class DealerStatusPageCopyAdmin(PageCopyAdminMixin, admin.ModelAdmin):
    list_display = ("label", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 3})},
    }
    fieldsets = (
        ("Meta", {"fields": ("meta_title", "meta_description")}),
        ("Header", {
            "fields": (
                "brand_word_white",
                "brand_word_red",
                "header_badge_label",
                "nav_store_label",
                "nav_cart_label",
                "nav_dealers_label",
                "nav_services_label",
            )
        }),
        ("Hero", {
            "fields": (
                "hero_eyebrow",
                "hero_title",
                "hero_lead",
                "hero_tier_label_prefix",
                "tier_default_label",
                "hero_discount_suffix",
                "hero_primary_cta_label",
                "hero_secondary_cta_label",
                "hero_stat_dealer_since_label",
                "hero_stat_pending_label",
                "hero_stat_lifetime_spend_label",
                "hero_stat_next_tier_label",
                "hero_stat_next_tier_suffix",
                "hero_stat_top_tier_label",
                "hero_stat_top_tier_value",
                "hero_disclaimer",
            )
        }),
        ("Dealer overview", {
            "fields": (
                "account_overview_title",
                "account_overview_badge_label",
                "account_metric_tier_label",
                "account_metric_discount_label",
                "account_metric_lifetime_spend_label",
                "account_metric_last_review_label",
                "progress_title",
                "progress_max_tier_badge",
                "progress_top_tier_label",
                "orders_title",
                "orders_badge_suffix",
                "orders_open_label",
                "orders_completed_label",
                "orders_most_recent_label",
                "orders_cta_label",
            )
        }),
        ("Resources", {
            "fields": (
                "resources_title",
                "resource_1_title",
                "resource_1_desc",
                "resource_1_cta_label",
                "resource_2_title",
                "resource_2_desc",
                "resource_2_cta_label",
                "resource_3_title",
                "resource_3_desc",
                "resource_3_cta_label",
            )
        }),
        ("Application status", {
            "fields": (
                "application_status_title",
                "application_status_not_submitted_badge",
                "application_pending_callout",
                "application_rejected_callout",
                "application_approved_callout",
                "application_none_callout",
                "application_metric_business_label",
                "application_metric_tier_label",
                "application_metric_submitted_label",
                "application_contact_cta_label",
                "application_apply_cta_label",
                "application_reapply_cta_label",
            )
        }),
        ("Tier ladder", {
            "fields": (
                "tier_ladder_title",
                "tier_ladder_badge_label",
                "tier_table_tier_label",
                "tier_table_min_spend_label",
                "tier_table_discount_label",
                "tier_table_notes_label",
                "tier_empty_label",
            )
        }),
        ("Timeline", {
            "fields": (
                "timeline_title",
                "timeline_in_progress_label",
            )
        }),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        if DealerStatusPageCopy.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Page")
    def label(self, obj):
        return "Dealer portal"


class EmailTemplateSettingsForm(forms.ModelForm):
    class Meta:
        model = EmailTemplateSettings
        fields = (
            "brand_name",
            "brand_tagline",
            "company_address",
            "company_phone",
            "company_website",
            "support_email",
            "accent_color",
            "dark_color",
            "bg_color",
        )
        widgets = {
            "company_website": forms.TextInput(attrs={"placeholder": "https://example.com"}),
            "support_email": forms.EmailInput(attrs={"placeholder": "support@example.com"}),
            "accent_color": forms.TextInput(attrs={"placeholder": "#d50000"}),
            "dark_color": forms.TextInput(attrs={"placeholder": "#0b0b0c"}),
            "bg_color": forms.TextInput(attrs={"placeholder": "#0b0b0c"}),
        }


class EmailTemplateAdminForm(forms.ModelForm):
    brand_name = forms.CharField(
        required=False,
        label="Brand name",
        help_text="Leave blank to use the site default.",
    )
    brand_tagline = forms.CharField(
        required=False,
        label="Brand tagline",
        help_text="Leave blank to use the site default.",
    )
    company_address = forms.CharField(
        required=False,
        label="Company address",
        help_text="Leave blank to use the site default.",
    )
    company_phone = forms.CharField(
        required=False,
        label="Company phone",
        help_text="Leave blank to use the site default.",
    )
    company_website = forms.CharField(
        required=False,
        label="Company website",
        help_text="Leave blank to use the site default.",
        widget=forms.TextInput(attrs={"placeholder": "https://example.com"}),
    )
    support_email = forms.EmailField(
        required=False,
        label="Support email",
        help_text="Leave blank to use the site default.",
        widget=forms.EmailInput(attrs={"placeholder": "support@example.com"}),
    )
    accent_color = forms.CharField(
        required=False,
        label="Accent color",
        help_text="Leave blank to use the site default (hex like #d50000).",
        widget=forms.TextInput(attrs={"placeholder": "#d50000"}),
    )
    dark_color = forms.CharField(
        required=False,
        label="Dark color",
        help_text="Leave blank to use the site default (hex like #0b0b0c).",
        widget=forms.TextInput(attrs={"placeholder": "#0b0b0c"}),
    )
    bg_color = forms.CharField(
        required=False,
        label="Background color",
        help_text="Leave blank to use the site default (hex like #0b0b0c).",
        widget=forms.TextInput(attrs={"placeholder": "#0b0b0c"}),
    )

    class Meta:
        model = EmailTemplate
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        settings_obj = EmailTemplateSettings.get_solo()
        self.fields["brand_name"].initial = settings_obj.brand_name or ""
        self.fields["brand_tagline"].initial = settings_obj.brand_tagline or ""
        self.fields["company_address"].initial = settings_obj.company_address or ""
        self.fields["company_phone"].initial = settings_obj.company_phone or ""
        self.fields["company_website"].initial = settings_obj.company_website or ""
        self.fields["support_email"].initial = settings_obj.support_email or ""
        self.fields["accent_color"].initial = settings_obj.accent_color or ""
        self.fields["dark_color"].initial = settings_obj.dark_color or ""
        self.fields["bg_color"].initial = settings_obj.bg_color or ""


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    form = EmailTemplateAdminForm
    list_display = ("name", "slug", "updated_at")
    search_fields = ("name", "subject", "title")
    readonly_fields = ("name", "slug", "description", "token_help", "created_at", "updated_at")
    change_list_template = "admin/core/emailtemplate/change_list.html"
    change_form_template = "admin/core/emailtemplate/change_form.html"
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 3})},
    }
    fieldsets = (
        ("Template", {"fields": ("name", "description", "slug", "token_help")}),
        ("Email settings (global)", {
            "fields": (
                "brand_name",
                "brand_tagline",
                "company_address",
                "company_phone",
                "company_website",
                "support_email",
                "accent_color",
                "dark_color",
                "bg_color",
            )
        }),
        ("Message", {"fields": ("subject", "preheader", "title", "greeting", "intro")}),
        ("Callout", {"fields": ("notice_title", "notice")}),
        ("Footer & button", {"fields": ("footer", "cta_label", "cta_url")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        settings_obj = EmailTemplateSettings.get_solo()
        settings_obj.brand_name = form.cleaned_data.get("brand_name", "") or ""
        settings_obj.brand_tagline = form.cleaned_data.get("brand_tagline", "") or ""
        settings_obj.company_address = form.cleaned_data.get("company_address", "") or ""
        settings_obj.company_phone = form.cleaned_data.get("company_phone", "") or ""
        settings_obj.company_website = form.cleaned_data.get("company_website", "") or ""
        settings_obj.support_email = form.cleaned_data.get("support_email", "") or ""
        settings_obj.accent_color = form.cleaned_data.get("accent_color", "") or ""
        settings_obj.dark_color = form.cleaned_data.get("dark_color", "") or ""
        settings_obj.bg_color = form.cleaned_data.get("bg_color", "") or ""
        settings_obj.save()

    @admin.display(description="Available placeholders")
    def token_help(self, obj):
        tokens = template_tokens(obj.slug)
        if not tokens:
            return "No placeholders."
        return ", ".join(f"{{{token}}}" for token in tokens)

    def _get_email_settings_form(self, request):
        settings_obj = EmailTemplateSettings.get_solo()
        if request.method == "POST" and request.POST.get("email_settings_submit") == "1":
            form = EmailTemplateSettingsForm(request.POST, instance=settings_obj)
            if form.is_valid():
                form.save()
                messages.success(request, "Email settings updated.")
                settings_obj = EmailTemplateSettings.get_solo()
            else:
                messages.error(request, "Please correct the highlighted fields.")
        else:
            form = EmailTemplateSettingsForm(instance=settings_obj)
        return form, settings_obj

    def _email_preview_defaults(self):
        return {
            "brand_name": email_brand_name(),
            "brand_tagline": email_brand_tagline(),
            "company_address": email_company_address(),
            "company_phone": email_company_phone(),
            "company_website": email_company_website(),
            "accent_color": email_accent_color(),
            "dark_color": email_dark_color(),
            "bg_color": email_bg_color(),
        }

    def changelist_view(self, request, extra_context=None):
        form, settings_obj = self._get_email_settings_form(request)

        extra_context = extra_context or {}
        extra_context["email_settings_form"] = form
        extra_context["email_settings_updated_at"] = settings_obj.updated_at
        return super().changelist_view(request, extra_context=extra_context)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["email_preview_defaults"] = self._email_preview_defaults()
        extra_context["email_settings_url"] = reverse("admin:core_emailtemplate_changelist")
        return super().changeform_view(
            request,
            object_id=object_id,
            form_url=form_url,
            extra_context=extra_context,
        )


class EmailSubscriberImportForm(forms.Form):
    file = forms.FileField(
        label="Email list file",
        help_text="Upload CSV or XLSX. Any column that contains email addresses will be imported.",
    )
    reactivate = forms.BooleanField(
        required=False,
        initial=True,
        label="Reactivate existing emails",
        help_text="If an email already exists but is inactive, turn it back on.",
    )


@admin.register(EmailSubscriber)
class EmailSubscriberAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ("email", "source", "is_active", "added_by", "created_at")
    list_filter = ("source", "is_active", ("created_at", DateFieldListFilter))
    search_fields = ("email",)
    readonly_fields = ("created_at", "updated_at")
    change_list_template = "admin/core/emailsubscriber/change_list.html"

    fieldsets = (
        ("Subscriber", {"fields": ("email", "source", "is_active", "added_by")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def get_urls(self):
        urls = super().get_urls()
        opts = self.model._meta
        custom_urls = [
            path(
                "import/",
                self.admin_site.admin_view(self.import_view),
                name=f"{opts.app_label}_{opts.model_name}_import",
            ),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        opts = self.model._meta
        try:
            extra_context["import_url"] = reverse(
                f"admin:{opts.app_label}_{opts.model_name}_import"
            )
        except Exception:
            extra_context["import_url"] = None
        return super().changelist_view(request, extra_context=extra_context)

    def import_view(self, request):
        opts = self.model._meta
        changelist_url = reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")

        if request.method == "POST":
            form = EmailSubscriberImportForm(request.POST, request.FILES)
            if form.is_valid():
                file_obj = form.cleaned_data["file"]
                reactivate = form.cleaned_data["reactivate"]
                try:
                    results = import_email_subscribers(
                        file_obj,
                        added_by=request.user,
                        reactivate=reactivate,
                    )
                except Exception as exc:
                    messages.error(request, f"Import failed: {exc}")
                else:
                    messages.success(
                        request,
                        "Imported {created} new emails. "
                        "Reactivated {reactivated}. "
                        "Skipped {skipped}.".format(**results),
                    )
                    if results.get("invalid"):
                        messages.warning(
                            request,
                            f"Skipped {results['invalid']} invalid email value(s).",
                        )
                    return HttpResponseRedirect(changelist_url)
        else:
            form = EmailSubscriberImportForm()

        context = {
            **self.admin_site.each_context(request),
            "opts": opts,
            "app_label": opts.app_label,
            "form": form,
            "changelist_url": changelist_url,
            "title": "Import email subscribers",
        }
        return TemplateResponse(request, "admin/core/emailsubscriber/import.html", context)

    def save_model(self, request, obj, form, change):
        if not obj.added_by:
            obj.added_by = request.user
        super().save_model(request, obj, form, change)


class EmailCampaignAdminForm(forms.ModelForm):
    send_now = forms.BooleanField(
        required=False,
        label="Send now",
        help_text="Send immediately after saving. Sent campaigns are locked for editing.",
    )

    class Meta:
        model = EmailCampaign
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = getattr(self, "instance", None)
        if instance and instance.pk and instance.status != EmailCampaign.Status.DRAFT:
            self.fields["send_now"].disabled = True
            self.fields["send_now"].help_text = "Already sent or sending."


@admin.register(EmailCampaign)
class EmailCampaignAdmin(admin.ModelAdmin):
    form = EmailCampaignAdminForm
    change_form_template = "admin/core/emailcampaign/change_form.html"
    list_display = (
        "name",
        "status_badge",
        "audience_total_display",
        "sent_summary",
        "send_button",
        "send_completed_at",
        "updated_at",
    )
    list_filter = ("status", "include_subscribers", "include_registered_users", "created_at")
    search_fields = ("name", "subject", "title")
    readonly_fields = (
        "status",
        "token_help",
        "audience_preview",
        "recipients_total",
        "sent_count",
        "failed_count",
        "send_started_at",
        "send_completed_at",
        "sent_by",
        "recipients_link",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("Campaign", {"fields": ("name", "status", "from_email", "send_now", "token_help")}),
        ("Content", {"fields": ("subject", "preheader", "title", "greeting", "intro")}),
        ("Callout", {"fields": ("notice_title", "notice")}),
        ("Footer & button", {"fields": ("footer", "cta_label", "cta_url")}),
        ("Audience", {"fields": ("include_subscribers", "include_registered_users", "audience_preview")}),
        ("Delivery", {
            "fields": (
                "sent_by",
                "send_started_at",
                "send_completed_at",
                "recipients_total",
                "sent_count",
                "failed_count",
                "recipients_link",
            )
        }),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
    actions = ("send_selected_campaigns",)

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            EmailCampaign.Status.DRAFT: "#64748b",
            EmailCampaign.Status.SENDING: "#0ea5e9",
            EmailCampaign.Status.SENT: "#16a34a",
            EmailCampaign.Status.PARTIAL: "#f97316",
            EmailCampaign.Status.FAILED: "#dc2626",
        }
        color = colors.get(obj.status, "#64748b")
        return format_html(
            '<span style="padding:0.2rem 0.6rem;border-radius:999px;background:{}1a;color:{};font-size:0.85rem;">{}</span>',
            color,
            color,
            obj.get_status_display(),
        )

    @admin.display(description="Audience size")
    def audience_total_display(self, obj):
        if obj.recipients_total:
            return obj.recipients_total
        counts = estimate_campaign_audience(obj)
        total = counts.get("estimated_total", 0)
        return total or "—"

    @admin.display(description="Sent")
    def sent_summary(self, obj):
        if not obj.recipients_total:
            return "—"
        return f"{obj.sent_count}/{obj.recipients_total}"

    @admin.display(description="Available placeholders")
    def token_help(self, obj):
        tokens = [
            "{brand}",
            "{support_email}",
            "{company_website}",
            "{company_phone}",
            "{first_name}",
            "{last_name}",
            "{full_name}",
            "{email}",
        ]
        return ", ".join(tokens)

    @admin.display(description="Audience preview")
    def audience_preview(self, obj):
        if not obj or not obj.pk:
            return "Save the campaign to see the audience size."
        counts = estimate_campaign_audience(obj)
        parts = []
        if obj.include_subscribers:
            parts.append(f"Subscribers: {counts['subscriber_count']}")
        if obj.include_registered_users:
            parts.append(f"Registered users (consent): {counts['user_count']}")
        if not parts:
            return "No audience selected."
        parts.append("Duplicates are removed when sending.")
        return mark_safe("<br>".join(parts))

    @admin.display(description="Preview")
    def preview_block(self, obj):
        if not obj or not obj.pk:
            return "Save the campaign to preview."
        content = render_campaign_email(obj)
        return format_html(
            "<div><strong>Subject:</strong> {}</div>"
            "<div><strong>Preheader:</strong> {}</div>"
            "<div style=\"margin-top:6px; white-space:pre-wrap;\">{}</div>",
            content.subject,
            content.preheader or "—",
            content.text_body or "—",
        )

    @admin.display(description="Recipients")
    def recipients_link(self, obj):
        if not obj or not obj.pk:
            return "—"

    @admin.display(description="Actions")
    def send_button(self, obj):
        if obj.status not in {
            EmailCampaign.Status.DRAFT,
            EmailCampaign.Status.PARTIAL,
            EmailCampaign.Status.FAILED,
        }:
            return "—"
        try:
            url = reverse("admin:core_emailcampaign_send", args=[obj.pk])
        except Exception:
            return "—"
        return format_html('<a class="button" href="{}">Send</a>', url)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:campaign_id>/send/",
                self.admin_site.admin_view(self.send_view),
                name="core_emailcampaign_send",
            ),
        ]
        return custom_urls + urls

    def _email_preview_defaults(self):
        return {
            "brand_name": email_brand_name(),
            "brand_tagline": email_brand_tagline(),
            "company_address": email_company_address(),
            "company_phone": email_company_phone(),
            "company_website": email_company_website(),
            "accent_color": email_accent_color(),
            "dark_color": email_dark_color(),
            "bg_color": email_bg_color(),
        }

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["email_preview_defaults"] = self._email_preview_defaults()
        extra_context["email_settings_url"] = reverse("admin:core_emailtemplate_changelist")
        return super().changeform_view(
            request,
            object_id=object_id,
            form_url=form_url,
            extra_context=extra_context,
        )

    def send_view(self, request, campaign_id):
        campaign = self.get_object(request, campaign_id)
        if campaign is None:
            return HttpResponseRedirect(reverse("admin:core_emailcampaign_changelist"))
        if not self.has_change_permission(request, campaign):
            raise PermissionDenied

        if request.method == "POST":
            try:
                result = send_campaign(campaign, triggered_by=request.user)
            except Exception as exc:
                messages.error(request, f"Send failed: {exc}")
            else:
                status = result.get("status")
                if status in {EmailCampaign.Status.SENT, EmailCampaign.Status.PARTIAL}:
                    messages.success(
                        request,
                        f"Campaign sent. {result.get('sent', 0)} sent, {result.get('failed', 0)} failed.",
                    )
                elif status == "no_recipients":
                    messages.warning(request, "Campaign has no recipients.")
                elif status == "skipped":
                    messages.warning(request, "Campaign already sent.")
                else:
                    messages.error(request, "Campaign send failed.")
            return HttpResponseRedirect(reverse("admin:core_emailcampaign_changelist"))

        counts = estimate_campaign_audience(campaign)
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "campaign": campaign,
            "audience_counts": counts,
            "title": "Send email campaign",
        }
        return TemplateResponse(request, "admin/core/emailcampaign/send_confirm.html", context)
        try:
            url = reverse("admin:core_emailcampaignrecipient_changelist")
            return format_html('<a href="{}?campaign__id__exact={}">View recipients</a>', url, obj.pk)
        except Exception:
            return "—"

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj and obj.status != EmailCampaign.Status.DRAFT:
            readonly.extend(
                [
                    "name",
                    "from_email",
                    "subject",
                    "preheader",
                    "title",
                    "greeting",
                    "intro",
                    "notice_title",
                    "notice",
                    "footer",
                    "cta_label",
                    "cta_url",
                    "include_subscribers",
                    "include_registered_users",
                ]
            )
        return readonly

    @admin.action(description="Send selected campaigns now")
    def send_selected_campaigns(self, request, queryset):
        sent = 0
        failed = 0
        skipped = 0
        for campaign in queryset:
            try:
                result = send_campaign(campaign, triggered_by=request.user)
            except Exception as exc:
                failed += 1
                messages.error(request, f"{campaign.name}: {exc}")
                continue
            status = result.get("status")
            if status in {EmailCampaign.Status.SENT, EmailCampaign.Status.PARTIAL}:
                sent += 1
            elif status == "skipped":
                skipped += 1
            else:
                failed += 1
        if sent:
            messages.success(request, f"Sent {sent} campaign(s).")
        if skipped:
            messages.warning(request, f"Skipped {skipped} campaign(s) (already sent).")
        if failed:
            messages.error(request, f"Failed to send {failed} campaign(s).")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if form.cleaned_data.get("send_now"):
            try:
                result = send_campaign(obj, triggered_by=request.user)
            except Exception as exc:
                messages.error(request, f"Send failed: {exc}")
                return
            status = result.get("status")
            if status in {EmailCampaign.Status.SENT, EmailCampaign.Status.PARTIAL}:
                messages.success(
                    request,
                    f"Campaign sent. {result.get('sent', 0)} sent, {result.get('failed', 0)} failed.",
                )
            elif status == "no_recipients":
                messages.warning(request, "Campaign has no recipients.")
            elif status == "skipped":
                messages.warning(request, "Campaign already sent.")
            else:
                messages.error(request, "Campaign send failed.")


@admin.register(EmailCampaignRecipient)
class EmailCampaignRecipientAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ("email", "campaign", "status", "source", "sent_at")
    list_filter = ("campaign", "status", "source", ("sent_at", DateFieldListFilter))
    search_fields = ("email", "campaign__name", "user__email")
    readonly_fields = ("campaign", "email", "user", "source", "status", "error_message", "sent_at", "created_at")


@admin.register(EmailSendLog)
class EmailSendLogAdmin(admin.ModelAdmin):
    list_display = ("email_type", "recipient_count", "success", "sent_at", "subject")
    list_filter = ("email_type", "success", ("sent_at", DateFieldListFilter))
    search_fields = ("subject", "from_email", "recipients")
    readonly_fields = (
        "email_type",
        "subject",
        "from_email",
        "recipients",
        "recipient_count",
        "success",
        "error_message",
        "sent_at",
    )

class ProjectJournalPhotoInline(admin.TabularInline):
    model = ProjectJournalPhoto
    extra = 1
    fields = ("kind", "image", "alt_text", "sort_order")
    ordering = ("sort_order", "created_at")


@admin.register(ProjectJournalEntry)
class ProjectJournalEntryAdmin(admin.ModelAdmin):
    list_display = ("title", "status_badge", "featured", "published_at", "updated_at", "preview_link")
    list_filter = ("status", "featured", "published_at")
    search_fields = (
        "title",
        "excerpt",
        "overview",
        "parts",
        "customizations",
        "backstory",
        "body",
        "tags",
        "client_name",
        "location",
        "services",
    )
    ordering = ("-published_at", "-updated_at")
    readonly_fields = ("created_at", "updated_at", "published_at", "preview_link")
    prepopulated_fields = {"slug": ("title",)}
    inlines = (ProjectJournalPhotoInline,)
    fieldsets = (
        ("Story", {
            "fields": (
                "title",
                "slug",
                "headline",
                "excerpt",
                "cover_image",
                "result_highlight",
            )
        }),
        ("Photo comparison (manual URLs)", {
            "fields": (
                "before_gallery",
                "after_gallery",
            ),
            "classes": ("collapse",),
        }),
        ("Build breakdown", {
            "fields": (
                "overview",
                "parts",
                "customizations",
                "backstory",
            )
        }),
        ("Full report", {"fields": ("body",)}),
        ("Project meta", {
            "fields": (
                "client_name",
                "location",
                "services",
                "reading_time",
                "tags",
            )
        }),
        ("Publication", {
            "fields": (
                "status",
                "featured",
                "published_at",
                "preview_link",
                "created_at",
                "updated_at",
            )
        }),
    )
    actions = ("mark_as_published", "mark_as_draft")

    @admin.display(description="Status")
    def status_badge(self, obj):
        color = "#16a34a" if obj.status == obj.Status.PUBLISHED else "#f97316"
        return format_html(
            '<span style="padding:0.2rem 0.6rem;border-radius:999px;background:{}1a;color:{};font-size:0.85rem;">{}</span>',
            color,
            color,
            obj.get_status_display(),
        )

    @admin.display(description="Preview")
    def preview_link(self, obj):
        if not obj.pk:
            return "—"
        try:
            url = obj.get_absolute_url()
        except Exception:
            return "—"
        return format_html('<a href="{}" target="_blank" rel="noopener">Open page</a>', url)

    @admin.action(description="Publish selected posts")
    def mark_as_published(self, request, queryset):
        updated = 0
        for entry in queryset:
            if entry.status != entry.Status.PUBLISHED:
                entry.status = entry.Status.PUBLISHED
                entry.save()
                updated += 1
        self.message_user(request, f"Published {updated} post(s).")

    @admin.action(description="Move selected posts to draft")
    def mark_as_draft(self, request, queryset):
        updated = 0
        for entry in queryset:
            if entry.status != entry.Status.DRAFT:
                entry.status = entry.Status.DRAFT
                entry.save()
                updated += 1
        self.message_user(request, f"Moved {updated} post(s) to draft.")


@admin.register(HeroImage)
class HeroImageAdmin(admin.ModelAdmin):
    list_display = ("location", "title", "is_active", "updated_at", "image_preview")
    list_editable = ("is_active",)
    search_fields = ("title", "alt_text", "caption")
    list_filter = ("is_active", "location")
    readonly_fields = ("image_preview", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("location", "title", "is_active")}),
        ("Media", {"fields": ("image", "image_preview", "alt_text", "caption")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(BackgroundAsset)
class BackgroundAssetAdmin(admin.ModelAdmin):
    list_display = ("title", "is_active", "updated_at", "image_preview")
    list_editable = ("is_active",)
    search_fields = ("title", "alt_text", "caption")
    list_filter = ("is_active",)
    readonly_fields = ("image_preview", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("title", "is_active")}),
        ("Media", {"fields": ("image", "image_preview", "alt_text", "caption")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(SiteBackgroundSettings)
class SiteBackgroundSettingsAdmin(admin.ModelAdmin):
    list_display = ("label", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("default_background",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Settings")
    def label(self, obj):
        return "Site background"

    def has_add_permission(self, request):
        if SiteBackgroundSettings.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(ServiceLead)
class ServiceLeadAdmin(admin.ModelAdmin):
    list_display = ("created_at", "full_name", "service_needed", "phone", "email", "source_page", "status")
    list_filter = ("status", "source_page", "created_at")
    search_fields = (
        "full_name",
        "phone",
        "email",
        "vehicle",
        "service_needed",
        "notes",
        "source_url",
    )
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)
    fieldsets = (
        (None, {"fields": ("status", "source_page", "source_url")}),
        ("Contact", {"fields": ("full_name", "phone", "email")}),
        ("Vehicle & request", {"fields": ("vehicle", "service_needed", "notes")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(LeadSubmissionEvent)
class LeadSubmissionEventAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "form_type",
        "outcome",
        "success",
        "suspicion_score",
        "ip_address",
        "ip_location",
        "cf_country",
        "cf_asn",
    )
    list_filter = ("form_type", "outcome", "success", "created_at")
    search_fields = (
        "ip_address",
        "user_agent",
        "referer",
        "origin",
        "path",
        "session_key_hash",
        "cf_asn",
        "cf_asn_org",
    )
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
    fieldsets = (
        (None, {"fields": ("form_type", "outcome", "success", "suspicion_score")}),
        ("Request", {"fields": ("path", "referer", "origin", "accept_language", "user_agent")}),
        ("Network", {"fields": ("ip_address", "ip_location", "cf_country", "cf_asn", "cf_asn_org")}),
        ("Session", {"fields": ("session_key_hash", "session_first_seen_at", "time_on_page_ms")}),
        ("Diagnostics", {"fields": ("validation_errors", "flags", "created_at")}),
    )


@admin.register(VisitorSession)
class VisitorSessionAdmin(admin.ModelAdmin):
    list_display = (
        "session_key",
        "user_display",
        "ip_address",
        "ip_location",
        "landing_path",
        "created_at",
        "last_seen_at",
    )
    search_fields = (
        "session_key",
        "user__username",
        "user_email_snapshot",
        "user_name_snapshot",
        "ip_address",
        "ip_location",
    )
    list_filter = ("created_at", "last_seen_at")
    readonly_fields = ("created_at", "last_seen_at")
    ordering = ("-last_seen_at",)

    def user_display(self, obj):
        if obj.user_name_snapshot:
            return obj.user_name_snapshot
        if obj.user:
            return obj.user.get_full_name() or obj.user.username
        return "—"

    user_display.short_description = "User"


@admin.register(PageView)
class PageViewAdmin(admin.ModelAdmin):
    list_display = ("path", "session", "user", "duration_ms", "started_at")
    search_fields = ("path", "page_instance_id", "session__session_key", "user__username")
    list_filter = ("started_at",)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-started_at",)


@admin.register(ClientUiCheckRun)
class ClientUiCheckRunAdmin(admin.ModelAdmin):
    list_display = (
        "started_at",
        "status",
        "trigger",
        "total_pages",
        "failures_count",
        "warnings_count",
    )
    list_filter = ("status", "trigger", "started_at")
    search_fields = ("summary",)
    readonly_fields = (
        "trigger",
        "status",
        "started_at",
        "finished_at",
        "duration_ms",
        "total_pages",
        "total_links",
        "total_forms",
        "total_buttons",
        "failures_count",
        "warnings_count",
        "skipped_count",
        "summary",
        "report",
        "triggered_by",
    )
    ordering = ("-started_at",)
