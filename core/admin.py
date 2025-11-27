from bisect import bisect_left

from django.contrib.admin import DateFieldListFilter

from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.contrib import admin
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
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import json
import csv
from django.urls import path, reverse, NoReverseMatch
from django.http import HttpResponse
from .filters import *
from .models import *
from .forms import *
from core.services.analytics import summarize_web_analytics
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
        start_of_day = make_aware(datetime.combine(selected_date, datetime.min.time()))
        end_of_day = make_aware(datetime.combine(selected_date, datetime.max.time()))

        availabilities = MasterAvailability.objects.filter(
            start_time__lte=end_of_day,
            end_time__gte=start_of_day
        )
        appointments = appointments.filter(start_time__gte=start_of_day, start_time__lte=end_of_day)
        if request.GET.get("service"):
            appointments = appointments.filter(service_id=request.GET["service"])
        if request.GET.get("status"):
            appointments = appointments.filter(appointmentstatushistory__status_id=request.GET["status"])
        if request.GET.get("payment_status"):
            appointments = appointments.filter(payment_status_id__in=request.GET.getlist("payment_status"))

        appointments_for_day = list(appointments)
        slot_times = []
        grid_start, grid_end = determine_calendar_window(masters, appointments_for_day)
        calendar_table = createTable(selected_date, grid_start, grid_end, slot_times, appointments_for_day, masters, availabilities)


        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            action = request.GET.get("action")

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

        response = super().changelist_view(request, extra_context=extra_context)

        if hasattr(response, "context_data"):
            context = response.context_data
            context.update({
                "calendar_table": calendar_table,
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
    list_display = ('appointment', 'amount', 'method')
    list_filter = ('method',)
    export_fields = ['appointment', 'amount', 'method']
    search_fields = (
        'appointment__client__first_name', 'appointment__client__last_name',
        'appointment__master__first_name', 'appointment__master__last_name',
        'appointment__service__name',
    )


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
    COLOR_PALETTE = ["#E4D08A", "#EDC2A2", "#CEAEC6", "#A3C1C9", "#C3CEA3", "#E7B3C3"]
    master_ids = [m.id for m in masters]
    MASTER_COLORS = dict(zip(master_ids, cycle(COLOR_PALETTE)))


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
                                            <div style="font-size:1.8vh;">
                                                {local_start.strftime('%I:%M').lstrip('0')} – {local_end.strftime('%I:%M').lstrip('0')}
                                                <strong>{escape(client_name)}</strong>
                                            </div>
                                            <div style="font-size:1.8vh;">
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


@admin.register(ProjectJournalEntry)
class ProjectJournalEntryAdmin(admin.ModelAdmin):
    list_display = ("title", "status_badge", "featured", "published_at", "updated_at", "preview_link")
    list_filter = ("status", "featured", "published_at")
    search_fields = ("title", "excerpt", "body", "tags", "client_name", "location", "services")
    ordering = ("-published_at", "-updated_at")
    readonly_fields = ("created_at", "updated_at", "published_at", "preview_link")
    prepopulated_fields = {"slug": ("title",)}
    fieldsets = (
        ("Story", {
            "fields": (
                "title",
                "slug",
                "headline",
                "excerpt",
                "body",
                "cover_image",
                "result_highlight",
            )
        }),
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


@admin.register(VisitorSession)
class VisitorSessionAdmin(admin.ModelAdmin):
    list_display = (
        "session_key",
        "user_display",
        "ip_address",
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
