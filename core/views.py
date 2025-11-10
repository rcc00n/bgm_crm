# core/views.py
from django.shortcuts import render, get_object_or_404
from django.db.models import Prefetch, Q
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse, HttpResponseBadRequest
from datetime import datetime
import json
from django.utils.functional import cached_property

from core.models import (
    Appointment, ServiceCategory, Service, CustomUserDisplay,
    AppointmentStatusHistory, LegalPage, ProjectJournalEntry
)
from core.services.booking import (
    get_available_slots, get_service_masters,
    get_or_create_status, get_default_payment_status, _tz_aware
)
from core.validators import clean_phone

def _build_catalog_context(request):
    """Общий конструктор контекста каталога."""
    q = (request.GET.get("q") or "").strip()
    cat = request.GET.get("cat") or ""

    services_qs = Service.objects.select_related("category").order_by("name")
    if q:
        services_qs = services_qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
    if cat:
        services_qs = services_qs.filter(category__id=cat)

    categories_qs = (
        ServiceCategory.objects.order_by("name")
        .prefetch_related(Prefetch("service_set", queryset=services_qs))
    )

    return {
        "categories": categories_qs,
        "filter_categories": ServiceCategory.objects.order_by("name"),
        "q": q,
        "active_category": str(cat),
        "search_results": services_qs if q else None,
        "has_any_services": services_qs.exists(),
        "uncategorized": services_qs.filter(category__isnull=True),
    }

@ensure_csrf_cookie
def public_mainmenu(request):
    """
    Публичная главная страница (каталог). Доступна всем.
    Если пользователь авторизован — дополнительно подставим профиль и его записи.
    """
    ctx = _build_catalog_context(request)
    ctx["contact_prefill"] = {"name": "", "email": "", "phone": ""}

    if request.user.is_authenticated:
        user = request.user
        profile = getattr(user, "userprofile", None)
        ctx["profile"] = profile
        ctx["appointments"] = (
            Appointment.objects
            .filter(client=user)
            .select_related("service", "master")
            .order_by("-start_time")
        )
        ctx["contact_prefill"] = {
            "name": user.get_full_name() or user.username or "",
            "email": user.email or "",
            "phone": getattr(profile, "phone", "") if profile else "",
        }
    else:
        # чтобы шаблон не спотыкался, если где-то используешь эти ключи
        ctx.setdefault("profile", None)
        ctx.setdefault("appointments", [])

    return render(request, "client/mainmenu.html", ctx)

# ===== API =====

@require_GET
def api_availability(request):
    service_id = request.GET.get("service")
    date_str = request.GET.get("date")
    master_id = request.GET.get("master")

    if not service_id or not date_str:
        return HttpResponseBadRequest("service and date required")

    service = get_object_or_404(Service.objects.select_related("category"), pk=service_id)
    day = parse_date(date_str)
    if not day:
        return HttpResponseBadRequest("invalid date")

    day_dt = _tz_aware(datetime(day.year, day.month, day.day, 12, 0))
    master_obj = get_object_or_404(CustomUserDisplay, pk=master_id) if master_id else None
    slots_map = get_available_slots(service, day_dt, master=master_obj)

    masters_qs = [master_obj] if master_obj else list(get_service_masters(service))
    resp = {
        "service": {"id": str(service.pk), "name": service.name, "duration": service.duration_min},
        "date": date_str,
        "masters": []
    }
    for m in masters_qs:
        mp = getattr(m, "master_profile", None)
        avatar_url = ""
        if mp and getattr(mp, "photo", None):
            try:
                avatar_url = mp.photo.url
            except Exception:
                avatar_url = ""
        resp["masters"].append({
            "id": m.id,
            "name": m.get_full_name() or m.username,
            "avatar": avatar_url,
            "slots": [s.isoformat() for s in slots_map.get(m.id, [])]
        })
    return JsonResponse(resp)

@require_POST
@csrf_protect
def api_book(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        from django.http import HttpResponseBadRequest
        return HttpResponseBadRequest("invalid json")

    service_id = payload.get("service")
    master_id  = payload.get("master")
    start_iso  = payload.get("start_time")

    if not service_id or not master_id or not start_iso:
        return HttpResponseBadRequest("service, master, start_time required")

    service = get_object_or_404(Service, pk=service_id)
    master  = get_object_or_404(CustomUserDisplay, pk=master_id)

    if not get_service_masters(service).filter(pk=master.pk).exists():
        from django.http import HttpResponseBadRequest
        return HttpResponseBadRequest("master can't perform this service")

    try:
        start_dt = parse_datetime(start_iso) or _tz_aware(datetime.fromisoformat(start_iso))
        if not timezone.is_aware(start_dt):
            start_dt = _tz_aware(start_dt)
    except Exception:
        from django.http import HttpResponseBadRequest
        return HttpResponseBadRequest("invalid start_time")

    contact = payload.get("contact") or {}
    contact_name = (contact.get("name") or "").strip()
    contact_email = (contact.get("email") or "").strip()
    raw_phone = (contact.get("phone") or "").strip()
    digits_only = "".join(ch for ch in raw_phone if ch.isdigit())
    contact_phone = ""
    if digits_only:
        contact_phone = f"+{digits_only}" if raw_phone.strip().startswith("+") else digits_only

    user = request.user if request.user.is_authenticated else None
    if user:
        contact_name = contact_name or user.get_full_name() or user.username or ""
        contact_email = contact_email or user.email or ""
        profile = getattr(user, "userprofile", None)
        fallback_phone = getattr(profile, "phone", "") if profile else ""
        contact_phone = contact_phone or fallback_phone

    contact_errors = {}
    if not contact_name:
        contact_errors["name"] = "Name is required."
    if not contact_email:
        contact_errors["email"] = "Email is required."
    else:
        try:
            validate_email(contact_email)
        except ValidationError:
            contact_errors["email"] = "Enter a valid email."
    if not contact_phone:
        contact_errors["phone"] = "Phone is required."
    else:
        try:
            contact_phone = clean_phone(contact_phone)
        except ValidationError:
            contact_errors["phone"] = "Enter a valid phone number in international format."

    if contact_errors:
        return JsonResponse({"errors": {"contact": contact_errors}}, status=400)

    contact_name = contact_name[:120]
    pay_status = get_default_payment_status()
    appt = Appointment(
        client=user,
        contact_name=contact_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        master=master,
        service=service,
        start_time=start_dt,
        payment_status=pay_status if pay_status else None,
    )
    try:
        appt.full_clean()
    except ValidationError as exc:
        return JsonResponse({"errors": exc.message_dict or exc.messages}, status=400)
    appt.save()

    initial_status = get_or_create_status("Confirmed")
    AppointmentStatusHistory.objects.create(
        appointment=appt,
        status=initial_status,
        set_by=user,
    )

    return JsonResponse({
        "ok": True,
        "appointment": {
            "id": str(appt.pk),
            "service": service.name,
            "master": master.get_full_name() or master.username,
            "start_time": appt.start_time.isoformat(),
        }
    }, status=201)

# --- API: отмена/перенос записи ---
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.db import transaction

from core.models import (
    Appointment, AppointmentStatus, AppointmentStatusHistory,
    CustomUserDisplay, ServiceMaster
)

def _status(name: str) -> AppointmentStatus:
    obj, _ = AppointmentStatus.objects.get_or_create(name=name)
    return obj

@login_required
@require_POST
@csrf_protect
def api_appointment_cancel(request, appt_id):
    appt = get_object_or_404(Appointment.objects.select_related("client", "service", "master"), pk=appt_id)
    # только владелец или staff
    if not (request.user.is_staff or appt.client_id == request.user.id):
        return HttpResponseForbidden("not allowed")

    cancelled = _status("Cancelled")
    # уже отменена?
    if appt.appointmentstatushistory_set.filter(status=cancelled).exists():
        return JsonResponse({"ok": True, "already": True})

    with transaction.atomic():
        AppointmentStatusHistory.objects.create(
            appointment=appt,
            status=cancelled,
            set_by=request.user,
        )
    return JsonResponse({"ok": True})

@login_required
@require_POST
@csrf_protect
def api_appointment_reschedule(request, appt_id):
    """
    JSON: { "start_time": "<ISO8601>", "master": <user_id optional> }
    Меняет время (и по желанию мастера) с валидацией Appointment.clean().
    """
    appt = get_object_or_404(Appointment.objects.select_related("client", "service", "master"), pk=appt_id)
    if not (request.user.is_staff or appt.client_id == request.user.id):
        return HttpResponseForbidden("not allowed")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("invalid json")

    start_iso = payload.get("start_time")
    if not start_iso:
        return HttpResponseBadRequest("start_time required")

    # разбираем дату/время
    try:
        new_start = parse_datetime(start_iso) or _tz_aware(datetime.fromisoformat(start_iso))
        if not timezone.is_aware(new_start):
            new_start = _tz_aware(new_start)
    except Exception:
        return HttpResponseBadRequest("invalid start_time")

    # смена мастера (опционально)
    master_id = payload.get("master")
    if master_id:
        new_master = get_object_or_404(CustomUserDisplay, pk=master_id)
        # мастер должен уметь услугу
        if not ServiceMaster.objects.filter(service=appt.service, master=new_master).exists():
            return HttpResponseBadRequest("master can't perform this service")
        appt.master = new_master

    appt.start_time = new_start

    # валидация пересечений/комнат/отпусков
    appt.full_clean()
    with transaction.atomic():
        appt.save()
        # история статусов
        AppointmentStatusHistory.objects.create(
            appointment=appt,
            status=_status("Rescheduled"),
            set_by=request.user,
        )

    return JsonResponse({"ok": True, "appointment": {
        "id": str(appt.pk),
        "start_time": appt.start_time.isoformat(),
        "master": appt.master.get_full_name() or appt.master.username
    }})


@require_GET
def service_search(request):
    q = (request.GET.get('q') or '').strip()
    cat = request.GET.get('cat') or ''
    qs = Service.objects.select_related('category')

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
    if cat:
        qs = qs.filter(category_id=cat)

    qs = qs.order_by('name')[:60]  # limit

    results = []
    for s in qs:
        disc = s.get_active_discount() if not s.contact_for_estimate else None
        base_price = str(s.base_price_amount())
        price = None
        if not s.contact_for_estimate:
            price = str(s.get_discounted_price()) if disc else base_price
        results.append({
            "id": str(s.id),
            "name": s.name,
            "category": s.category.name if s.category_id else "",
            "description": (s.description or "")[:280],
            "base_price": base_price,
            "price": price,
            "contact_for_estimate": s.contact_for_estimate,
            "estimate_from_price": str(s.estimate_from_price) if s.estimate_from_price is not None else "",
            "discount_percent": disc.discount_percent if disc else None,
            "duration_min": s.duration_min,
            # NEW: image url for cards
            "image": s.image.url if getattr(s, "image", None) else "",
        })
    return JsonResponse({"results": results})

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView

from core.forms import DealerApplicationForm
from core.models import DealerApplication
from core.services.dealer_portal import build_portal_snapshot

class DealerApplyView(LoginRequiredMixin, CreateView):
    template_name = "core/dealer/apply.html"
    form_class = DealerApplicationForm
    success_url = reverse_lazy("dealer-status")

    def dispatch(self, request, *args, **kwargs):
        profile = getattr(request.user, "userprofile", None)
        if profile and profile.is_dealer:
            return redirect("dealer-status")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        # initial пригодится clean() для проверки дублей
        kwargs.setdefault("initial", {})["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        # Один активный аппликейшен на пользователя (кроме REJECTED)
        if DealerApplication.objects.filter(user=self.request.user).exclude(
            status=DealerApplication.Status.REJECTED
        ).exists():
            form.add_error(None, "You already have an application in progress or approved.")
            return self.form_invalid(form)
        form.instance.user = self.request.user
        return super().form_valid(form)


class DealerStatusView(LoginRequiredMixin, TemplateView):
    template_name = "core/dealer/status.html"

    def get_contextDataBase(self, **kwargs):
        # оставлено намеренно неверным именем метода; используйте get_context_data ниже
        pass

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        up = getattr(self.request.user, "userprofile", None)
        dealer_app = getattr(self.request.user, "dealer_application", None)
        ctx["userprofile"] = up
        ctx["dealer_application"] = dealer_app
        # флаг доступа и snapshot для портала
        portal_snapshot = build_portal_snapshot(self.request.user)
        ctx["portal"] = portal_snapshot
        ctx["application_steps"] = portal_snapshot.get("timeline", [])
        ctx["orders_snapshot"] = portal_snapshot.get("orders") or {"total": 0, "open": 0, "completed": 0, "latest": None}
        ctx["tier_levels"] = portal_snapshot.get("tiers", [])
        ctx["next_tier"] = portal_snapshot.get("next_tier")
        ctx["current_threshold"] = portal_snapshot.get("current_threshold")
        ctx["remaining_to_next"] = portal_snapshot.get("remaining_to_next")
        ctx["lifetime_spent"] = portal_snapshot.get("lifetime_spent")
        ctx["is_dealer"] = portal_snapshot.get("is_dealer", False)
        return ctx

from django.shortcuts import render

def financing_view(request):
    return render(request, "financing.html")

def our_story_view(request):
    return render(request, "client/our_story.html")


def project_journal_view(request):
    tag_filter = (request.GET.get("tag") or "").strip()
    normalized_tag = tag_filter.lower()

    published_posts = list(ProjectJournalEntry.objects.published())
    available_tags = sorted(
        {tag for post in published_posts for tag in post.tag_list},
        key=lambda tag: tag.lower(),
    )

    if normalized_tag:
        visible_posts = [
            post for post in published_posts
            if any(tag.lower() == normalized_tag for tag in post.tag_list)
        ]
    else:
        visible_posts = published_posts

    featured_post = next((post for post in visible_posts if post.featured), None)
    if not featured_post and visible_posts:
        featured_post = visible_posts[0]

    remaining_posts = [
        post for post in visible_posts
        if not featured_post or post.pk != featured_post.pk
    ]

    context = {
        "featured_post": featured_post,
        "journal_posts": remaining_posts,
        "available_tags": available_tags,
        "tag_filter": tag_filter,
        "has_posts": bool(visible_posts),
        "page_title": "Project Journal",
        "meta_description": "Quiet corner of Bad Guy Motors where we document completed builds, wraps, and custom work.",
    }
    return render(request, "client/project_journal.html", context)


class LegalPageView(TemplateView):
    """
    Generic renderer for editable legal/marketing documents.
    """
    template_name = "legal/page.html"
    slug = None

    @cached_property
    def page(self) -> LegalPage:
        lookup_slug = self.kwargs.get("slug") or self.slug
        queryset = LegalPage.objects.filter(is_active=True)
        return get_object_or_404(queryset, slug=lookup_slug)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page"] = self.page
        ctx.setdefault("meta_title", self.page.title)
        return ctx


class TermsAndConditionsView(LegalPageView):
    slug = "terms-and-conditions"

# core/views.py
from datetime import datetime, timedelta
from django.db.models import Sum, Count, F
from django.utils import timezone
from django.shortcuts import render

from core.models import (
    Appointment, AppointmentStatusHistory, Payment,
    ClientReview, Service, CustomUserDisplay
)
from store.models import Order, OrderItem

def admin_dashboard(request):
    """Главная страница админки с расширенной статистикой."""
    today = timezone.localdate()
    start_date = today - timedelta(days=6)  # за последние 7 дней

    # 1. Выручка по дням (по платежам)
    payments = (
        Payment.objects.filter(created_at__date__gte=start_date)
        .annotate(day=F("created_at__date"))
        .values("day")
        .annotate(total=Sum("amount"))
        .order_by("day")
    )
    chart_data = [
        {"day": p["day"].strftime("%d.%m"), "sales": float(p["total"])}
        for p in payments
    ]

    # 2. Число подтверждённых и отменённых записей по дням
    appointments = (
        AppointmentStatusHistory.objects
        .filter(set_at__date__gte=start_date)
        .annotate(day=F("set_at__date"))
        .values("day", "status__name")
        .annotate(cnt=Count("id"))
    )
    # агрегируем в словарь вида {"2025-09-10": {"Confirmed": 2, "Cancelled": 1}, ...}
    appt_stats_by_day = {}
    for item in appointments:
        day = item["day"].strftime("%d.%m")
        status = item["status__name"]
        appt_stats_by_day.setdefault(day, {"Confirmed": 0, "Cancelled": 0})
        appt_stats_by_day[day][status] = item["cnt"]
    daily_appointments = [
        {
            "day": day,
            "confirmed": appt_stats_by_day[day]["Confirmed"],
            "cancelled": appt_stats_by_day[day]["Cancelled"],
        }
        for day in sorted(appt_stats_by_day.keys())
    ]

    # 3. Количество записей сегодня (по статусам)
    today_appointments_qs = Appointment.objects.filter(
        start_time__date=today
    )
    confirmed_count = today_appointments_qs.filter(
        appointmentstatushistory__status__name="Confirmed"
    ).count()
    cancelled_count = today_appointments_qs.filter(
        appointmentstatushistory__status__name="Cancelled"
    ).count()
    total_today = today_appointments_qs.count()

    # 4. Топ‑услуги по количеству записей
    top_services = (
        Appointment.objects.filter(start_time__date__gte=start_date)
        .values("service__name")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")[:5]
    )

    # 5. Топ‑мастера по выручке (сумма платежей за их услуги)
    top_masters = (
        Payment.objects.filter(appointment__start_time__date__gte=start_date)
        .values("appointment__master__first_name", "appointment__master__last_name")
        .annotate(total=Sum("amount"))
        .order_by("-total")[:5]
    )

    # 6. Средняя оценка клиентов
    avg_rating = ClientReview.objects.aggregate(avg=Sum("rating") * 1.0 / Count("rating"))["avg"]

    # 7. Статистика магазина: общая выручка и количество заказов
    orders_completed = Order.objects.filter(status=Order.STATUS_COMPLETED)
    store_revenue = orders_completed.aggregate(
        total=Sum(F("items__price_at_moment") * F("items__qty"))
    )["total"] or 0
    orders_count = orders_completed.count()

    context = {
        "today": today,
        "chart_data": chart_data,
        "daily_appointments": daily_appointments,
        "confirmed_count": confirmed_count,
        "cancelled_count": cancelled_count,
        "total_today": total_today,
        "top_services": top_services,
        "top_masters": top_masters,
        "avg_rating": avg_rating,
        "store_revenue": store_revenue,
        "orders_count": orders_count,
        # передаём существующие переменные, если они используются
        "recent_appointments": [],  # заполните при необходимости
    }
    return render(request, "admin/index.html", context)
