# core/views.py
from django.shortcuts import render, get_object_or_404
from django.db.models import Prefetch, Q
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_protect
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
from datetime import datetime
import json

from core.models import (
    Appointment, ServiceCategory, Service, CustomUserDisplay,
    AppointmentStatusHistory
)
from core.services.booking import (
    get_available_slots, get_service_masters,
    get_or_create_status, get_default_payment_status, _tz_aware
)

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

def public_mainmenu(request):
    """
    Публичная главная страница (каталог). Доступна всем.
    Если пользователь авторизован — дополнительно подставим профиль и его записи.
    """
    ctx = _build_catalog_context(request)

    if request.user.is_authenticated:
        user = request.user
        ctx["profile"] = getattr(user, "userprofile", None)
        ctx["appointments"] = (
            Appointment.objects
            .filter(client=user)
            .select_related("service", "master")
            .order_by("-start_time")
        )
    else:
        # чтобы шаблон не спотыкался, если где-то используешь эти ключи
        ctx.setdefault("profile", None)
        ctx.setdefault("appointments", [])

    return render(request, "client/mainmenu.html", ctx)

# ===== API (оставляем только для авторизованных) =====

@login_required
@require_GET
def api_availability(request):
    service_id = request.GET.get("service")
    date_str = request.GET.get("date")
    master_id = request.GET.get("master")

    if not service_id or not date_str:
        from django.http import HttpResponseBadRequest
        return HttpResponseBadRequest("service and date required")

    service = get_object_or_404(Service.objects.select_related("category"), pk=service_id)
    day = parse_date(date_str)
    if not day:
        from django.http import HttpResponseBadRequest
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
        resp["masters"].append({
            "id": m.id,
            "name": m.get_full_name() or m.username,
            "slots": [s.isoformat() for s in slots_map.get(m.id, [])]
        })
    from django.http import JsonResponse
    return JsonResponse(resp)

@login_required
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
        from django.http import HttpResponseBadRequest
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

    pay_status = get_default_payment_status()
    appt = Appointment(
        client=request.user,
        master=master,
        service=service,
        start_time=start_dt,
        payment_status=pay_status if pay_status else None,
    )
    appt.full_clean()
    appt.save()

    initial_status = get_or_create_status("Confirmed")
    AppointmentStatusHistory.objects.create(
        appointment=appt,
        status=initial_status,
        set_by=request.user,
    )

    from django.http import JsonResponse
    return JsonResponse({
        "ok": True,
        "appointment": {
            "id": str(appt.pk),
            "service": service.name,
            "master": master.get_full_name() or master.username,
            "start_time": appt.start_time.isoformat(),
        }
    }, status=201)
