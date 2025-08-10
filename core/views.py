from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.db.models import Prefetch, Q

from core.models import Appointment, ServiceCategory, Service

@login_required
def client_dashboard(request):
    user = request.user

    # Личные данные/записи клиента (старый функционал сохранён)
    profile = getattr(user, "userprofile", None)
    appointments = (
        Appointment.objects
        .filter(client=user)
        .select_related("service", "master")
        .order_by("-start_time")
    )

    # Каталог
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

    context = {
        "profile": profile,
        "appointments": appointments,
        "categories": categories_qs,                          # блоки каталога
        "filter_categories": ServiceCategory.objects.order_by("name"),  # селект
        "q": q,
        "active_category": str(cat),
        "search_results": services_qs if q else None,
        "has_any_services": services_qs.exists(),
        "uncategorized": services_qs.filter(category__isnull=True),
    }
    return render(request, "client/mainmenu.html", context)

# core/views.py (добавь импорты)
import json
from datetime import datetime
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.contrib.auth.decorators import login_required
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
from django.shortcuts import get_object_or_404

from core.models import Service, CustomUserDisplay, Appointment, AppointmentStatusHistory
from core.services.booking import (
    get_available_slots, get_service_masters,
    get_or_create_status, get_default_payment_status, _tz_aware
)

# ... твоя client_dashboard как есть ...


@login_required
@require_GET
def api_availability(request):
    """
    GET /accounts/api/availability/?service=<uuid>&date=YYYY-MM-DD[&master=<id>]
    Ответ: { service: ..., date: ..., masters: [{id, name, slots:[iso...]}, ...] }
    """
    service_id = request.GET.get("service")
    date_str = request.GET.get("date")
    master_id = request.GET.get("master")

    if not service_id or not date_str:
        return HttpResponseBadRequest("service and date required")

    service = get_object_or_404(Service.objects.select_related("category"), pk=service_id)
    day = parse_date(date_str)
    if not day:
        return HttpResponseBadRequest("invalid date")

    # формируем tz-aware "полдень" той даты — для расчёта окна
    day_dt = _tz_aware(datetime(day.year, day.month, day.day, 12, 0))

    master_obj = None
    if master_id:
        master_obj = get_object_or_404(CustomUserDisplay, pk=master_id)

    slots_map = get_available_slots(service, day_dt, master=master_obj)

    # собираем мастеров для ответа (если мастер не задан, все по услуге)
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
    return JsonResponse(resp)


@login_required
@require_POST
@csrf_protect
def api_book(request):
    """
    POST /accounts/api/book/
    JSON: { "service": "<uuid>", "master": <user_id>, "start_time": "<ISO8601>" }
    Создаёт Appointment, пишет историю статусов.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("invalid json")

    service_id = payload.get("service")
    master_id = payload.get("master")
    start_iso = payload.get("start_time")

    if not service_id or not master_id or not start_iso:
        return HttpResponseBadRequest("service, master, start_time required")

    service = get_object_or_404(Service, pk=service_id)
    master = get_object_or_404(CustomUserDisplay, pk=master_id)

    # проверим, что мастер умеет услугу
    if not get_service_masters(service).filter(pk=master.pk).exists():
        return HttpResponseBadRequest("master can't perform this service")

    # разбираем дату/время
    try:
        # допускаем как полный ISO, так и 'YYYY-MM-DDTHH:MM'
        start_dt = parse_datetime(start_iso) or _tz_aware(datetime.fromisoformat(start_iso))
        if not timezone.is_aware(start_dt):
            start_dt = _tz_aware(start_dt)
    except Exception:
        return HttpResponseBadRequest("invalid start_time")

    # создаём запись
    pay_status = get_default_payment_status()
    appt = Appointment(
        client=request.user,
        master=master,
        service=service,
        start_time=start_dt,
        payment_status=pay_status if pay_status else None,
    )

    # валидации модели (пересечения, комнаты, отпуска)
    appt.full_clean()  # вызовет Appointment.clean()
    appt.save()

    # первичный статус в истории
    initial_status = get_or_create_status("Confirmed")
    AppointmentStatusHistory.objects.create(
        appointment=appt,
        status=initial_status,
        set_by=request.user,
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
