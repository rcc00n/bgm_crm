from bisect import bisect_left

from django.contrib.admin import DateFieldListFilter

from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.contrib import admin
from django.db.models import Sum, Count
from itertools import cycle
from django.utils.timezone import localtime, datetime, make_aware, localdate
from django.utils.html import escape
from django.utils.html import format_html
from django.utils.safestring import mark_safe
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

    master_role = Role.objects.filter(name="Master").first()
    first_day = today.replace(day=1)
    masters = CustomUserDisplay.objects.filter(userrole__role=master_role).annotate(
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
        ('Files', {'fields': ('files',)}),
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
        if db_field.name == "master":
            master_role = Role.objects.filter(name="Master").first()
            if master_role:
                master_user_ids = UserRole.objects.filter(role=master_role).values_list('user_id', flat=True)
                kwargs["queryset"] = CustomUserDisplay.objects.filter(id__in=master_user_ids)
            else:
                kwargs["queryset"] = User.objects.none()
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
    fields = ['client', 'master', 'service', 'start_time', 'payment_status', 'status']
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

        appointments = Appointment.objects.select_related('client', 'service', 'master')
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
        if hasattr(request.user, "master_profile"):
            masters = CustomUserDisplay.objects.filter(id=request.user.id)
        else:
            masters = CustomUserDisplay.objects.filter(
                id__in=appointments.values_list('master_id', flat=True)
            ).distinct()
        start_of_day = make_aware(datetime.combine(selected_date, datetime.min.time()))
        end_of_day = make_aware(datetime.combine(selected_date, datetime.max.time()))

        availabilities = MasterAvailability.objects.filter(
            start_time__lte=end_of_day,
            end_time__gte=start_of_day
        )
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

            calendar_table = createTable(selected_date, time_pointer, end_time, slot_times, appointments, masters, availabilities)

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

        calendar_table = createTable(selected_date, time_pointer, end_time, slot_times, appointments, masters, availabilities)

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
    list_display = ('user', "uploaded_by" ,'file_type', 'file')
    fields = ('user', 'file',"uploaded_by", 'file_type')
    readonly_fields = ('file_type',)  # 👈 делаем только для чтения
    exclude = ('file_type',)  # 👈 скрываем из формы создания
    list_filter = (('uploaded_at', DateFieldListFilter), 'file_type')
    search_fields = ('user__first_name', 'user__last_name')
    ordering = ['-uploaded_at']



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
        return obj.appointment.client.get_full_name()

    @admin.display(description="Staff")
    def get_master(self, obj):
        return obj.appointment.master.get_full_name()


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

def createTable(selected_date, time_pointer, end_time, slot_times, appointments, masters, availabilities):
    COLOR_PALETTE = ["#E4D08A", "#EDC2A2", "#CEAEC6", "#A3C1C9", "#C3CEA3", "#E7B3C3"]
    master_ids = [m.id for m in masters]
    MASTER_COLORS = dict(zip(master_ids, cycle(COLOR_PALETTE)))


    while time_pointer <= end_time:
        slot_times.append(time_pointer.strftime('%H:%M'))
        time_pointer += timedelta(minutes=15)

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
        base_duration = getattr(service, "duration_min", 0) or 0
        extra_duration = getattr(service, "extra_time_min", 0) or 0
        duration = base_duration + extra_duration
        rowspan = max(1, duration // 15)

        slot_map.setdefault(master_id, {})
        skip_map.setdefault(master_id, {})

        slot_map[master_id][time_key] = {
            "appointment": appt,
            "rowspan": rowspan,
        }

        for i in range(1, rowspan):
            t = local_start + timedelta(minutes=i * 15)
            skip_map[master_id][t.strftime('%H:%M')] = True

    # --- Vacations / Breaks ---

    availability_map = {}

    for period in availabilities:
        master_id = int(getattr(period.master, "id", period.master))
        start = localtime(period.start_time)
        end = localtime(period.end_time)

        if start.date() <= selected_date <= end.date():
            day_start = datetime.combine(selected_date, time(8, 0)).replace(tzinfo=start.tzinfo)
            day_end = datetime.combine(selected_date, time(21, 15)).replace(tzinfo=end.tzinfo)

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
                appt_promocode = getattr(appt, 'appointmentpromocode', None)

                local_start = localtime(appt.start_time)
                local_end = local_start + timedelta(minutes=appt.service.duration_min) + timedelta(minutes=appt.service.extra_time_min)
                last_status = appt.appointmentstatushistory_set.order_by('-set_at').first()
                status_name = last_status.status.name if last_status else "Unknown"
                service_obj = appt.service
                if service_obj.contact_for_estimate:
                    price_value = "Contact for estimate"
                    price_discounted = price_value
                else:
                    price_discounted = f"${service_obj.get_discounted_price():.2f}"
                    price_value = f"${service_obj.base_price_amount():.2f}"

                row["cells"].append({
                    "html": f"""
                                        <div>
                                            <div style="font-size:1.8vh;">
                                                {local_start.strftime('%I:%M').lstrip('0')} – {local_end.strftime('%I:%M').lstrip('0')}
                                                <strong>{escape(appt.client.get_full_name())}</strong>
                                            </div>
                                            <div style="font-size:1.8vh;">
                                                {escape(appt.service.name)}
                                            </div>
                                        </div>
                                    """,
                    "rowspan": data["rowspan"],
                    "appt_id": appt.id,
                    "appointment": appt,
                    "client": escape(appt.client.get_full_name()),
                    "phone": escape("+1 " + getattr(appt.client.userprofile, "phone", "")),
                    "service": escape(appt.service.name),
                    "status": status_name,
                    "master": escape(master.get_full_name()),
                    "time_label": f"{local_start.strftime('%I:%M%p').lstrip('0')} - {local_end.strftime('%I:%M%p').lstrip('0')}",
                    "duration": f"{appt.service.duration_min}min",
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
from core.models import DealerApplication, UserProfile

# ──────────────────────────────────────────────────────────────────────────────
# Dealer Applications
# ──────────────────────────────────────────────────────────────────────────────

@admin.register(DealerApplication)
class DealerApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "user", "business_name", "status",
        "created_at", "reviewed_by", "reviewed_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("user__email", "user__username", "business_name", "phone", "website")
    readonly_fields = ("created_at", "reviewed_at", "reviewed_by")

    actions = ["approve_selected", "reject_selected"]

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
            return f"${obj.total_spent_usd():,.2f}"
        except Exception:
            return "$0.00"

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
