# core/views.py
import logging

from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.db.models import Prefetch, Q
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt, csrf_protect, ensure_csrf_cookie
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme
from datetime import datetime
import json
from django.utils.functional import cached_property

from core.emails import build_email_html, send_html_email
from core.models import (
    Appointment,
    ServiceCategory,
    Service,
    CustomUserDisplay,
    AppointmentStatusHistory,
    LegalPage,
    ProjectJournalEntry,
    PageView,
    VisitorSession,
    PageFontSetting,
    LandingPageReview,
    PromoCode,
    SiteNoticeSignup,
)
from core.forms import ServiceLeadForm
from core.services.booking import (
    get_available_slots, get_service_masters,
    get_or_create_status, get_default_payment_status, _tz_aware
)
from core.validators import clean_phone
from core.services.fonts import build_page_font_context
from core.services.media import (
    build_brake_suspension_media,
    build_electrical_work_media,
    build_performance_tuning_media,
)
from notifications.services import notify_about_service_lead

logger = logging.getLogger(__name__)

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


def _get_landing_reviews(page_slug: str):
    """
    Fetch published landing-page reviews in display order.
    """
    return (
        LandingPageReview.objects.filter(page=page_slug, is_published=True)
        .order_by("display_order", "-created_at")
    )

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


@staff_member_required
@require_GET
def admin_client_contact(request, user_id):
    """
    Lightweight endpoint for the admin calendar form to fetch contact data for a linked client.
    """
    user = get_object_or_404(
        CustomUserDisplay.objects.select_related("userprofile"),
        pk=user_id,
    )
    profile = getattr(user, "userprofile", None)
    return JsonResponse({
        "id": user.id,
        "name": user.get_full_name() or user.username or user.email or "",
        "email": user.email or "",
        "phone": getattr(profile, "phone", "") if profile else "",
    })

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
from core.models import DealerApplication, DealerTierLevel
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

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        try:
            ctx["tier_levels"] = list(
                DealerTierLevel.objects.filter(is_active=True).order_by("minimum_spend", "sort_order", "code")
            )
        except Exception:
            ctx["tier_levels"] = []
        return ctx

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


def brake_suspension_view(request):
    media = build_brake_suspension_media()
    font_settings = build_page_font_context(PageFontSetting.Page.BRAKE_SUSPENSION)
    reviews = _get_landing_reviews(LandingPageReview.Page.BRAKE_SUSPENSION)
    return render(
        request,
        "client/brake_suspension.html",
        {"brake_media": media, "font_settings": font_settings, "reviews": reviews},
    )


def electrical_work_view(request):
    media = build_electrical_work_media()
    font_settings = build_page_font_context(PageFontSetting.Page.ELECTRICAL_WORK)
    reviews = _get_landing_reviews(LandingPageReview.Page.ELECTRICAL_WORK)
    return render(
        request,
        "client/electrical_work.html",
        {"electrical_media": media, "font_settings": font_settings, "reviews": reviews},
    )


def wheel_tire_service_view(request):
    font_settings = build_page_font_context(PageFontSetting.Page.WHEEL_TIRE_SERVICE)
    return render(request, "client/wheel_tire_service.html", {"font_settings": font_settings})


def general_service_request_view(request):
    """
    Direct-link general request landing with the service lead form.
    """
    return render(request, "client/general_request.html")


def performance_tuning_view(request):
    media = build_performance_tuning_media()
    font_settings = build_page_font_context(PageFontSetting.Page.PERFORMANCE_TUNING)
    reviews = _get_landing_reviews(LandingPageReview.Page.PERFORMANCE_TUNING)
    return render(
        request,
        "client/performance_tuning.html",
        {"tuning_media": media, "font_settings": font_settings, "reviews": reviews},
    )


def _lead_redirect_target(request, *, fallback: str = "/") -> str:
    """
    Safely resolve where to send the user after submitting a landing lead.
    """
    candidates = [
        request.POST.get("next"),
        request.POST.get("source_url"),
        request.META.get("HTTP_REFERER"),
        fallback,
    ]
    for target in candidates:
        if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
            return target
    return fallback


def _resolve_site_notice_code() -> str:
    code = (getattr(settings, "SITE_NOTICE_PROMO_CODE", "") or "").strip()
    if code:
        return code.upper()
    try:
        today = timezone.now().date()
        promo = PromoCode.objects.filter(
            active=True,
            start_date__lte=today,
            end_date__gte=today,
            discount_percent=5,
        ).order_by("code").first()
        if promo and promo.code:
            return promo.code.upper()
    except Exception:
        logger.exception("Failed to resolve site notice promo code.")
    return "WELCOME5"


@require_POST
@csrf_protect
def site_notice_signup(request):
    """
    Capture popup email signups and send a welcome code.
    """
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

    def _error(message: str, status: int = 400):
        if is_ajax:
            return JsonResponse({"error": message}, status=status)
        messages.error(request, message)
        return HttpResponseRedirect(_lead_redirect_target(request))

    email = (request.POST.get("email") or "").strip()
    if not email and request.content_type and "application/json" in request.content_type:
        try:
            payload = json.loads(request.body.decode("utf-8"))
            email = (payload.get("email") or "").strip()
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            email = ""

    if not email:
        return _error("Email is required.")

    try:
        validate_email(email)
    except ValidationError:
        return _error("Enter a valid email.")

    sender = (
        getattr(settings, "DEFAULT_FROM_EMAIL", None)
        or getattr(settings, "SUPPORT_EMAIL", None)
    )
    if not sender:
        logger.warning("Missing DEFAULT_FROM_EMAIL/SUPPORT_EMAIL for site notice signup.")
        return _error("Email service is unavailable.", status=500)

    code = _resolve_site_notice_code()
    brand = getattr(settings, "SITE_BRAND_NAME", "Bad Guy Motors")
    subject = f"{brand} welcome code"
    text_lines = [
        f"Thanks for joining the {brand} email list.",
        f"Your welcome code: {code}",
        "Use it on any product or service invoice.",
        "",
        "Questions? Reply to this email and we will help.",
    ]

    try:
        html_body = build_email_html(
            title="Your 5% welcome code",
            preheader=f"Welcome code inside: {code}",
            greeting=f"Thanks for joining the {brand} email list.",
            intro_lines=[
                "Here is your welcome code for 5% off your first order.",
                "Use it on any product or service invoice.",
            ],
            summary_rows=[("Welcome code", code), ("Discount", "5% off")],
            footer_lines=["Questions? Reply to this email and we will help."],
            cta_label=f"Visit {brand}",
            cta_url=getattr(settings, "COMPANY_WEBSITE", ""),
        )
        send_html_email(
            subject=subject,
            text_body="\n".join(text_lines),
            html_body=html_body,
            from_email=sender,
            recipient_list=[email],
        )
    except Exception:
        logger.exception("Failed to send site notice code email to %s", email)
        return _error("Unable to send the code right now.", status=500)

    try:
        SiteNoticeSignup.objects.create(
            email=email,
            welcome_code=code,
            welcome_sent_at=timezone.now(),
        )
    except Exception:
        logger.exception("Failed to record site notice signup for %s", email)

    try:
        user = CustomUserDisplay.objects.filter(email__iexact=email).first()
        profile = getattr(user, "userprofile", None) if user else None
        if profile:
            profile.set_marketing_consent(True)
            profile.save(update_fields=["email_marketing_consent", "email_marketing_consented_at"])
    except Exception:
        logger.exception("Failed to update marketing consent for %s", email)

    if is_ajax:
        return JsonResponse({"ok": True, "message": "Check your inbox for your code."})

    messages.success(request, "Thanks! Check your inbox for your code.")
    return HttpResponseRedirect(_lead_redirect_target(request))


@require_POST
@csrf_protect
def submit_service_lead(request):
    """
    Capture marketing/landing page leads and fan out notifications.
    """
    form = ServiceLeadForm(request.POST)
    if form.is_valid():
        lead = form.save()
        notify_about_service_lead(lead.pk)
        messages.success(
            request,
            "Thanks! Your request reached our team. Expect a reply shortly.",
        )
        return HttpResponseRedirect(_lead_redirect_target(request))

    errors = [err for field_errors in form.errors.values() for err in field_errors]
    error_msg = "Please correct the highlighted fields and try again."
    if errors:
        error_msg = f"{error_msg} ({'; '.join(errors)})"
    messages.error(request, error_msg)
    return HttpResponseRedirect(_lead_redirect_target(request))


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


@require_POST
@csrf_exempt
def analytics_collect(request):
    """
    Accepts lightweight JSON payloads from the frontend tracker so we can
    persist dwell time and visit metadata.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    page_instance_id = (payload.get("page_instance_id") or "").strip()
    if not page_instance_id:
        return JsonResponse({"error": "page_instance_id is required."}, status=400)

    def _int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    duration_ms = max(0, _int(payload.get("duration_ms", 0)))
    timezone_offset = _int(payload.get("timezone_offset", 0))
    viewport_width = _int(payload.get("viewport_width")) or None
    viewport_height = _int(payload.get("viewport_height")) or None

    started_at_raw = payload.get("started_at")
    started_at = None
    if started_at_raw:
        try:
            started_at = parse_datetime(started_at_raw)
        except (TypeError, ValueError):
            started_at = None
    if started_at and not timezone.is_aware(started_at):
        started_at = timezone.make_aware(started_at)
    started_at = started_at or timezone.now()

    visitor_session = getattr(request, "visitor_session", None)
    if not visitor_session:
        session_key = request.session.session_key
        if not session_key:
            request.session.save()
            session_key = request.session.session_key
        visitor_session, _ = VisitorSession.objects.get_or_create(
            session_key=session_key,
            defaults={
                "ip_address": request.META.get("REMOTE_ADDR"),
                "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:1024],
                "landing_path": (request.path or "")[:512],
            },
        )

    user = request.user if request.user.is_authenticated else visitor_session.user
    path_value = (payload.get("path") or request.META.get("HTTP_REFERER") or "/")[:512]
    full_path_value = (payload.get("full_path") or path_value)[:768]

    base_defaults = {
        "session": visitor_session,
        "user": user,
        "path": path_value,
        "full_path": full_path_value,
        "page_title": (payload.get("title") or "")[:255],
        "referrer": (payload.get("referrer") or "")[:512],
        "started_at": started_at,
        "duration_ms": duration_ms,
        "timezone_offset": timezone_offset,
        "viewport_width": viewport_width,
        "viewport_height": viewport_height,
    }

    page_view, created = PageView.objects.get_or_create(
        page_instance_id=page_instance_id,
        defaults=base_defaults,
    )

    dirty = []
    if not created:
        if duration_ms and duration_ms > page_view.duration_ms:
            page_view.duration_ms = duration_ms
            dirty.append("duration_ms")
        if path_value and page_view.path != path_value:
            page_view.path = path_value
            dirty.append("path")
        if user and page_view.user_id != user.id:
            page_view.user = user
            dirty.append("user")
        if viewport_width and page_view.viewport_width != viewport_width:
            page_view.viewport_width = viewport_width
            dirty.append("viewport_width")
        if viewport_height and page_view.viewport_height != viewport_height:
            page_view.viewport_height = viewport_height
            dirty.append("viewport_height")
        # keep earliest started_at to describe the session accurately
        if started_at < page_view.started_at:
            page_view.started_at = started_at
            dirty.append("started_at")
        if not page_view.full_path and base_defaults["full_path"]:
            page_view.full_path = base_defaults["full_path"]
            dirty.append("full_path")
        if not page_view.page_title and base_defaults["page_title"]:
            page_view.page_title = base_defaults["page_title"]
            dirty.append("page_title")
        if dirty:
            page_view.save(update_fields=dirty)

    status = 201 if created else 200
    return JsonResponse({"ok": True}, status=status)

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
