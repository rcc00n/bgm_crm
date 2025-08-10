# core/services/booking.py
from __future__ import annotations
from datetime import datetime, timedelta, time
from typing import List, Dict, Optional, Tuple

from django.db.models import Q
from django.utils import timezone
from django.utils.timezone import make_aware, get_current_timezone

from core.models import (
    Service, ServiceMaster, CustomUserDisplay, Appointment,
    MasterAvailability, AppointmentStatus, AppointmentStatusHistory,
    PaymentStatus, MasterProfile,
)

Slot = Tuple[datetime, datetime]

def _tz_aware(dt: datetime) -> datetime:
    if timezone.is_aware(dt):
        return dt
    return make_aware(dt, get_current_timezone())

def _intervals_subtract(avail: Slot, blocks: List[Slot]) -> List[Slot]:
    """
    Вычитает блокировки (blocks) из доступного интервала avail,
    возвращает список свободных интервалов.
    """
    free = [avail]
    for b_start, b_end in sorted(blocks, key=lambda x: x[0]):
        next_free: List[Slot] = []
        for f_start, f_end in free:
            # нет пересечения
            if b_end <= f_start or b_start >= f_end:
                next_free.append((f_start, f_end))
                continue
            # обрезаем слева
            if b_start > f_start:
                next_free.append((f_start, b_start))
            # обрезаем справа
            if b_end < f_end:
                next_free.append((b_end, f_end))
        free = next_free
    return [(s, e) for s, e in free if e > s]

def _gen_slots_in_intervals(free_intervals: List[Slot], total_minutes: int, step_minutes: int = 15) -> List[datetime]:
    """
    Разбиваем свободные интервалы на слоты с шагом step_minutes так,
    чтобы целиком помещался отрезок длиной total_minutes.
    Возвращаем список стартов слотов (tz-aware).
    """
    out: List[datetime] = []
    step = timedelta(minutes=step_minutes)
    dur = timedelta(minutes=total_minutes)
    for s, e in free_intervals:
        start = s
        # выравниваем к ближайшему шагу
        if start.minute % step_minutes:
            align = step_minutes - (start.minute % step_minutes)
            start = start.replace(second=0, microsecond=0) + timedelta(minutes=align)
        while start + dur <= e:
            out.append(start)
            start += step
    return out

def _master_day_work_window(mp: MasterProfile, day: datetime) -> Slot:
    """
    Рабочее окно мастера на день (без учёта отпусков), tz-aware.
    """
    start_t: time = mp.work_start or time(8, 0)
    end_t: time = mp.work_end or time(21, 0)
    day = day.astimezone(get_current_timezone())
    ws = _tz_aware(datetime(day.year, day.month, day.day, start_t.hour, start_t.minute))
    we = _tz_aware(datetime(day.year, day.month, day.day, end_t.hour, end_t.minute))
    return ws, we

def _appointment_intervals(master: CustomUserDisplay, day: datetime) -> List[Slot]:
    """
    Интервалы занятости по существующим записям мастера на указанную дату.
    Исключаем отменённые.
    """
    start_day = _tz_aware(datetime(day.year, day.month, day.day, 0, 0)) - timedelta(hours=3)
    end_day = start_day + timedelta(days=1, hours=3)

    qs = (
        Appointment.objects
        .filter(master=master, start_time__gte=start_day, start_time__lt=end_day)
        .select_related("service")
    )

    # исключаем отменённые (если есть статус 'Cancelled')
    cancelled = AppointmentStatus.objects.filter(name__iexact="Cancelled").first()
    if cancelled:
        qs = qs.exclude(appointmentstatushistory__status=cancelled)

    blocks: List[Slot] = []
    for ap in qs:
        ap_start = ap.start_time
        dur = timedelta(minutes=ap.service.duration_min or 0)
        blocks.append((ap_start, ap_start + dur))
    return blocks

def _timeoff_intervals(master: CustomUserDisplay, day: datetime) -> List[Slot]:
    """
    Интервалы отпусков/перерывов мастера на дату.
    """
    start_day = _tz_aware(datetime(day.year, day.month, day.day, 0, 0))
    end_day = start_day + timedelta(days=1)
    qs = MasterAvailability.objects.filter(
        master=master,
        start_time__lt=end_day,
        end_time__gt=start_day
    )
    return [(p.start_time, p.end_time) for p in qs]

def get_service_masters(service: Service) -> CustomUserDisplay:
    """
    Список мастеров, которые умеют выполнять услугу.
    """
    master_ids = ServiceMaster.objects.filter(service=service).values_list("master_id", flat=True)
    return CustomUserDisplay.objects.filter(id__in=master_ids).select_related("master_profile")

def get_available_slots(
    service: Service,
    day: datetime,
    master: Optional[CustomUserDisplay] = None,
    step_minutes: int = 15
) -> Dict[int, List[datetime]]:
    """
    Возвращает словарь {master_id: [datetime слот-старты]} на дату day.
    Учитывает рабочее окно, существующие записи и периоды недоступности.
    """
    total_minutes = (service.duration_min or 0) + (service.extra_time_min or 0)
    day = day.astimezone(get_current_timezone())

    masters = [master] if master else list(get_service_masters(service))

    result: Dict[int, List[datetime]] = {}
    for m in masters:
        mp: Optional[MasterProfile] = getattr(m, "master_profile", None)
        if not mp:
            continue

        work_s, work_e = _master_day_work_window(mp, day)
        if work_s >= work_e:
            continue

        blocks = _appointment_intervals(m, day) + _timeoff_intervals(m, day)
        free = _intervals_subtract((work_s, work_e), blocks)
        slots = _gen_slots_in_intervals(free, total_minutes=total_minutes, step_minutes=step_minutes)
        if slots:
            result[m.id] = slots
        else:
            result[m.id] = []
    return result

def get_or_create_status(name: str) -> AppointmentStatus:
    obj, _ = AppointmentStatus.objects.get_or_create(name=name)
    return obj

def get_default_payment_status() -> Optional[PaymentStatus]:
    return (
        PaymentStatus.objects.filter(name__iexact="Pending").first()
        or PaymentStatus.objects.first()
    )
