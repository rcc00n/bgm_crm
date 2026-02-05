# core/views.py
import logging
import re

from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.db import models
from django.db.models import Prefetch, Q
from django.contrib import admin, messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.contenttypes.models import ContentType
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt, csrf_protect, ensure_csrf_cookie
from django.views.decorators.cache import never_cache
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
from django.utils.text import slugify
from django.utils.html import strip_tags
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
from django.template.response import TemplateResponse
from datetime import datetime, timedelta
import json
import html as py_html
from django.utils.functional import cached_property

from core.email_templates import base_email_context, email_brand_name, join_text_sections, render_email_template
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
    PageCopyDraft,
    FontPreset,
    PageSection,
    LandingPageReview,
    PromoCode,
    SiteNoticeSignup,
    ServicesPageCopy,
    FinancingPageCopy,
    AboutPageCopy,
    DealerStatusPageCopy,
    EmailCampaign,
    EmailSendLog,
    EmailSubscriber,
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
from core.services.page_sections import get_page_sections
from core.services.pagecopy_preview import PREVIEW_CONFIG
from core.services.lead_security import evaluate_lead_submission, log_lead_submission
from core.services.analytics import (
    summarize_staff_usage_periods,
    summarize_staff_action_history,
    summarize_web_analytics_insights,
)
from core.services.email_reporting import describe_email_types
from notifications.services import (
    notify_about_service_lead,
    notify_about_site_notice_signup,
    queue_lead_digest,
)

logger = logging.getLogger(__name__)


@require_http_methods(["GET", "POST"])
@csrf_protect
def admin_logout(request):
    logout(request)
    return redirect(getattr(settings, "LOGOUT_REDIRECT_URL", "/"))


def _resolve_pagecopy_model(label: str):
    label = (label or "").strip().lower()
    if not label:
        return None
    for model_cls in PREVIEW_CONFIG.keys():
        model_label = f"{model_cls._meta.app_label}.{model_cls._meta.model_name}".lower()
        if model_label == label:
            return model_cls
    return None


def _normalize_plain_value(value: str) -> str:
    text = (value or "").replace("\r", "")
    text = re.sub(r"<br\\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(div|p|li|h[1-6])>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<(div|p|li|h[1-6])[^>]*>", "", text, flags=re.IGNORECASE)
    text = strip_tags(text)
    text = py_html.unescape(text)
    return text


@staff_member_required
@require_POST
@csrf_protect
def admin_pagecopy_save_field(request):
    payload = {}
    if request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = {}
    if not payload:
        payload = request.POST.dict()

    model_label = (payload.get("model") or "").strip()
    field_name = (payload.get("field") or "").strip()
    object_id = payload.get("object_id") or payload.get("objectId")
    value = payload.get("value", "")

    if not model_label or not field_name:
        return JsonResponse({"ok": False, "error": "Missing parameters."}, status=400)

    model_cls = _resolve_pagecopy_model(model_label)
    if not model_cls:
        return JsonResponse({"ok": False, "error": "Unsupported model."}, status=400)

    if not request.user.has_perm(f"{model_cls._meta.app_label}.change_{model_cls._meta.model_name}"):
        raise PermissionDenied

    try:
        field_obj = model_cls._meta.get_field(field_name)
    except Exception:
        return JsonResponse({"ok": False, "error": "Unknown field."}, status=400)

    if not isinstance(field_obj, (models.CharField, models.TextField)):
        return JsonResponse({"ok": False, "error": "Field type not supported."}, status=400)

    try:
        object_id = int(object_id) if object_id is not None else None
    except (TypeError, ValueError):
        object_id = None

    obj = model_cls.objects.filter(pk=object_id).first() if object_id else model_cls.objects.first()
    if not obj:
        return JsonResponse({"ok": False, "error": "Object not found."}, status=404)

    if value is None:
        value = ""
    value = str(value)
    if isinstance(field_obj, models.CharField):
        value = _normalize_plain_value(value)
        if field_obj.max_length:
            value = value[: field_obj.max_length]

    content_type = ContentType.objects.get_for_model(model_cls)
    draft, _ = PageCopyDraft.objects.get_or_create(content_type=content_type, object_id=obj.pk)
    payload = draft.data or {}
    payload[field_name] = value
    draft.data = payload
    draft.save(update_fields=["data", "updated_at"])

    return JsonResponse({"ok": True, "draft": True, "field": field_name, "value": value})


@staff_member_required
@require_POST
@csrf_protect
def admin_pagecopy_save_draft(request):
    payload = {}
    if request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = {}
    if not payload:
        payload = request.POST.dict()

    model_label = (payload.get("model") or "").strip()
    object_id = payload.get("object_id") or payload.get("objectId")
    data = payload.get("data") or payload.get("fields") or payload.get("values") or {}

    if not model_label:
        return JsonResponse({"ok": False, "error": "Missing model."}, status=400)

    if not isinstance(data, dict):
        return JsonResponse({"ok": False, "error": "Invalid draft payload."}, status=400)

    model_cls = _resolve_pagecopy_model(model_label)
    if not model_cls:
        return JsonResponse({"ok": False, "error": "Unsupported model."}, status=400)

    if not request.user.has_perm(f"{model_cls._meta.app_label}.change_{model_cls._meta.model_name}"):
        raise PermissionDenied

    try:
        object_id = int(object_id) if object_id is not None else None
    except (TypeError, ValueError):
        object_id = None

    obj = model_cls.objects.filter(pk=object_id).first() if object_id else model_cls.objects.first()
    if not obj:
        return JsonResponse({"ok": False, "error": "Object not found."}, status=404)

    allowed = {
        field.name: field
        for field in model_cls._meta.get_fields()
        if isinstance(field, (models.CharField, models.TextField))
    }

    updated = {}
    draft = PageCopyDraft.for_instance(obj)
    payload_data = draft.data or {}
    for field_name, raw_value in data.items():
        field_obj = allowed.get(field_name)
        if not field_obj:
            continue
        value = "" if raw_value is None else str(raw_value)
        if isinstance(field_obj, models.CharField):
            value = _normalize_plain_value(value)
            if field_obj.max_length:
                value = value[: field_obj.max_length]
        payload_data[field_name] = value
        updated[field_name] = value

    if not updated:
        return JsonResponse({"ok": False, "error": "No draft fields."}, status=400)

    draft.data = payload_data
    draft.save(update_fields=["data", "updated_at"])

    return JsonResponse({"ok": True, "draft": True, "fields": list(updated.keys())})


@staff_member_required
@require_POST
@csrf_protect
def admin_pagecopy_save_section_layout(request):
    payload = {}
    if request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = {}
    if not payload:
        payload = request.POST.dict()

    section_id = payload.get("section_id") or payload.get("sectionId")
    mode = (payload.get("mode") or "desktop").strip().lower()
    layout = payload.get("layout") or {}

    if not section_id:
        return JsonResponse({"ok": False, "error": "Missing section id."}, status=400)

    try:
        section_id = int(section_id)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Invalid section id."}, status=400)

    if mode not in {"desktop", "mobile"}:
        mode = "desktop"

    if not request.user.has_perm("core.change_pagesection"):
        raise PermissionDenied

    section = PageSection.objects.filter(pk=section_id).first()
    if not section:
        return JsonResponse({"ok": False, "error": "Section not found."}, status=404)

    if not isinstance(layout, dict):
        layout = {}

    def _coerce_int(value, default=0):
        try:
            return int(round(float(value)))
        except Exception:
            return default

    def _coerce_width(value):
        if value is None or value == "":
            return None
        try:
            width = int(round(float(value)))
        except Exception:
            return None
        return width if width > 0 else None

    next_state = {
        "x": _coerce_int(layout.get("x", 0)),
        "y": _coerce_int(layout.get("y", 0)),
        "w": _coerce_width(layout.get("w")),
    }

    overrides = section.layout_overrides if isinstance(section.layout_overrides, dict) else {}
    if "desktop" not in overrides:
        overrides["desktop"] = {}
    if "mobile" not in overrides:
        overrides["mobile"] = {}

    if next_state["x"] or next_state["y"] or next_state["w"]:
        overrides[mode] = next_state
    else:
        overrides[mode] = {}

    section.layout_overrides = overrides
    section.save(update_fields=["layout_overrides", "updated_at"])

    return JsonResponse({"ok": True, "section_id": section.pk, "mode": mode, "layout": overrides.get(mode, {})})


@staff_member_required
@require_POST
@csrf_protect
def admin_pagecopy_save_section_order(request):
    payload = {}
    if request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = {}
    if not payload:
        payload = request.POST.dict()

    order = payload.get("order") or []
    model_label = (payload.get("model") or "").strip()
    object_id = payload.get("object_id") or payload.get("objectId")

    if not isinstance(order, list):
        return JsonResponse({"ok": False, "error": "Invalid order payload."}, status=400)
    if not order:
        return JsonResponse({"ok": False, "error": "Missing section order."}, status=400)

    if not request.user.has_perm("core.change_pagesection"):
        raise PermissionDenied

    resolved_ids = []
    for entry in order:
        try:
            resolved_ids.append(int(entry))
        except (TypeError, ValueError):
            continue

    if not resolved_ids:
        return JsonResponse({"ok": False, "error": "No valid section ids."}, status=400)

    filters = {"pk__in": resolved_ids}
    if model_label and object_id:
        model_cls = _resolve_pagecopy_model(model_label)
        if not model_cls:
            return JsonResponse({"ok": False, "error": "Unsupported model."}, status=400)
        try:
            object_id = int(object_id)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "Invalid object id."}, status=400)
        content_type = ContentType.objects.get_for_model(model_cls)
        filters.update({"content_type": content_type, "object_id": object_id})

    sections = list(PageSection.objects.filter(**filters))
    if not sections:
        return JsonResponse({"ok": False, "error": "Sections not found."}, status=404)

    allowed = {section.pk for section in sections}
    updates = []
    for idx, section_id in enumerate(resolved_ids):
        if section_id not in allowed:
            continue
        updates.append((section_id, idx))

    for section_id, next_order in updates:
        PageSection.objects.filter(pk=section_id).update(order=next_order)

    return JsonResponse({"ok": True, "order": resolved_ids})


@staff_member_required
@require_POST
@csrf_protect
def admin_pagecopy_save_fonts(request):
    payload = {}
    if request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = {}
    if not payload:
        payload = request.POST.dict()

    page = (payload.get("page") or "").strip()
    body_font_id = payload.get("body_font") or payload.get("bodyFont")
    heading_font_id = payload.get("heading_font") or payload.get("headingFont")
    ui_font_id = payload.get("ui_font") or payload.get("uiFont")

    if not page:
        return JsonResponse({"ok": False, "error": "Missing page."}, status=400)

    valid_pages = {choice for choice, _ in PageFontSetting.Page.choices}
    if page not in valid_pages:
        return JsonResponse({"ok": False, "error": "Unsupported page."}, status=400)

    if not request.user.has_perm("core.change_pagefontsetting"):
        raise PermissionDenied

    def _get_font(font_id):
        try:
            return FontPreset.objects.get(pk=int(font_id))
        except Exception:
            return None

    body_font = _get_font(body_font_id)
    heading_font = _get_font(heading_font_id)
    ui_font = _get_font(ui_font_id) if ui_font_id else None

    if not body_font or not heading_font:
        return JsonResponse({"ok": False, "error": "Invalid font selection."}, status=400)

    setting, _ = PageFontSetting.objects.get_or_create(
        page=page,
        defaults={"body_font": body_font, "heading_font": heading_font, "ui_font": ui_font},
    )
    setting.body_font = body_font
    setting.heading_font = heading_font
    setting.ui_font = ui_font
    setting.save(update_fields=["body_font", "heading_font", "ui_font", "updated_at"])

    return JsonResponse({"ok": True})


@staff_member_required
@require_POST
@csrf_protect
def admin_pagecopy_save_font_styles(request):
    payload = {}
    if request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = {}
    if not payload:
        payload = request.POST.dict()

    page = (payload.get("page") or "").strip()
    styles = payload.get("styles") or {}

    if not page:
        return JsonResponse({"ok": False, "error": "Missing page."}, status=400)

    valid_pages = {choice for choice, _ in PageFontSetting.Page.choices}
    if page not in valid_pages:
        return JsonResponse({"ok": False, "error": "Unsupported page."}, status=400)

    if not request.user.has_perm("core.change_pagefontsetting"):
        raise PermissionDenied

    if not isinstance(styles, dict):
        styles = {}

    allowed_transforms = {"none", "uppercase", "lowercase", "capitalize"}

    def _clean_style_value(value):
        if value is None:
            return ""
        if isinstance(value, (int, float)):
            value = str(value)
        text = str(value).strip()
        if not text:
            return ""
        text = re.sub(r"[;{}]", "", text)
        return text[:64]

    def _normalize_role(role_name):
        role_raw = styles.get(role_name)
        if not isinstance(role_raw, dict):
            return {}
        cleaned = {}
        for key in ("size", "weight", "line_height", "letter_spacing", "transform"):
            value = _clean_style_value(role_raw.get(key))
            if not value:
                continue
            if key == "transform" and value not in allowed_transforms:
                continue
            cleaned[key] = value
        return cleaned

    normalized = {}
    for role in ("body", "heading", "ui"):
        cleaned = _normalize_role(role)
        if cleaned:
            normalized[role] = cleaned

    setting = PageFontSetting.objects.filter(page=page).first()
    if not setting:
        fallback_font = FontPreset.objects.filter(is_active=True).order_by("name").first()
        if not fallback_font:
            return JsonResponse({"ok": False, "error": "Font presets not available."}, status=404)
        setting = PageFontSetting.objects.create(
            page=page,
            body_font=fallback_font,
            heading_font=fallback_font,
            ui_font=None,
        )

    setting.style_overrides = normalized
    setting.save(update_fields=["style_overrides", "updated_at"])

    return JsonResponse({"ok": True, "styles": normalized})


@staff_member_required
@require_POST
@csrf_protect
def admin_pagecopy_upload_font(request):
    if not request.user.has_perm("core.add_fontpreset"):
        raise PermissionDenied

    page = (request.POST.get("page") or "").strip()
    role = (request.POST.get("role") or "").strip()
    name = (request.POST.get("name") or "").strip()
    family = (request.POST.get("family") or "").strip()
    font_file = request.FILES.get("font_file")

    valid_pages = {choice for choice, _ in PageFontSetting.Page.choices}
    if page not in valid_pages:
        return JsonResponse({"ok": False, "error": "Unsupported page."}, status=400)
    if role not in {"body", "heading", "ui"}:
        return JsonResponse({"ok": False, "error": "Invalid role."}, status=400)
    if not font_file:
        return JsonResponse({"ok": False, "error": "Missing font file."}, status=400)

    font_name = name or font_file.name.rsplit(".", 1)[0]
    font_family = family or font_name
    base_slug = slugify(font_name)[:45] or "font"
    slug = base_slug
    counter = 2
    while FontPreset.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1

    preset = FontPreset.objects.create(
        slug=slug,
        name=font_name,
        font_family=font_family,
        font_file=font_file,
        mime_type=getattr(font_file, "content_type", "") or "font/ttf",
        preload=True,
        is_active=True,
    )

    if request.user.has_perm("core.change_pagefontsetting"):
        setting, _ = PageFontSetting.objects.get_or_create(
            page=page,
            defaults={"body_font": preset, "heading_font": preset, "ui_font": preset},
        )
        if role == "body":
            setting.body_font = preset
        elif role == "heading":
            setting.heading_font = preset
        else:
            setting.ui_font = preset
        setting.save(update_fields=["body_font", "heading_font", "ui_font", "updated_at"])

    return JsonResponse({"ok": True, "font": {"id": preset.pk, "name": preset.name}, "role": role})

def _normalize_search_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()

def _score_service_match(service, query: str, tokens):
    """
    Cheap relevance scoring: name matches outrank description matches.
    Returns 0 if there is no match at all.
    """
    if not query:
        return 0
    name = _normalize_search_text(service.name)
    desc = _normalize_search_text(service.description or "")
    if not name and not desc:
        return 0

    query = _normalize_search_text(query)
    if not query:
        return 0

    name_has_query = query in name
    desc_has_query = query in desc
    token_name_hits = sum(1 for t in tokens if t in name)
    token_desc_hits = sum(1 for t in tokens if t in desc)
    has_match = name_has_query or desc_has_query or token_name_hits or token_desc_hits
    if not has_match:
        return 0

    score = 0
    if name == query:
        score += 120
    if name.startswith(query):
        score += 90
    if name_has_query:
        score += 60
    if desc_has_query:
        score += 18
    if tokens:
        if token_name_hits == len(tokens):
            score += 40
        if token_desc_hits == len(tokens):
            score += 12
        score += token_name_hits * 12
        score += token_desc_hits * 4
    return score

def _rank_services(qs, query: str, limit: int = 60):
    services = list(qs)
    if not query:
        services.sort(key=lambda s: (s.name or "").lower())
        return services[:limit]

    tokens = [t for t in re.split(r"[^a-z0-9]+", _normalize_search_text(query)) if t]
    scored = [(s, _score_service_match(s, query, tokens)) for s in services]
    positive = [pair for pair in scored if pair[1] > 0]
    ranked = positive if positive else scored
    ranked.sort(key=lambda pair: (-pair[1], (pair[0].name or "").lower()))
    return [s for s, _ in ranked[:limit]]

def _is_mobile_request(request):
    if request.GET.get("desktop") == "1":
        return False
    if request.GET.get("mobile") == "1":
        return True
    ua = (request.META.get("HTTP_USER_AGENT") or "").lower()
    if not ua:
        return False
    mobile_markers = (
        "mobi", "android", "iphone", "ipod", "ipad", "windows phone",
        "blackberry", "opera mini", "opera mobi", "mobile"
    )
    return any(marker in ua for marker in mobile_markers)

def _build_catalog_context(request):
    """Общий конструктор контекста каталога."""
    q = (request.GET.get("q") or "").strip()
    cat = request.GET.get("cat") or ""
    filters_active = bool(q or cat)

    all_services_qs = Service.objects.select_related("category").order_by("name")
    filtered_qs = all_services_qs
    if cat:
        filtered_qs = filtered_qs.filter(category__id=cat)

    categories_qs = (
        ServiceCategory.objects.order_by("name")
        .prefetch_related(Prefetch("service_set", queryset=all_services_qs))
    )

    search_results = None
    if filters_active:
        search_results = _rank_services(filtered_qs, q, limit=60)
        if not search_results and all_services_qs.exists():
            search_results = _rank_services(all_services_qs, q, limit=60)

    return {
        "categories": categories_qs,
        "filter_categories": ServiceCategory.objects.filter(service__isnull=False).distinct().order_by("name"),
        "q": q,
        "active_category": str(cat),
        "filters_active": filters_active,
        "search_results": search_results,
        "has_any_services": all_services_qs.exists(),
        "uncategorized": all_services_qs.filter(category__isnull=True),
    }


def _get_landing_reviews(page_slug: str):
    """
    Fetch published landing-page reviews in display order.
    """
    return (
        LandingPageReview.objects.filter(page=page_slug, is_published=True)
        .order_by("display_order", "-created_at")
    )

@never_cache
@ensure_csrf_cookie
def public_mainmenu(request):
    """
    Публичная главная страница (каталог). Доступна всем.
    Если пользователь авторизован — дополнительно подставим профиль и его записи.
    """
    ctx = _build_catalog_context(request)
    ctx["services_copy"] = ServicesPageCopy.get_solo()
    ctx["header_copy"] = ctx["services_copy"]
    ctx["contact_prefill"] = {"name": "", "email": "", "phone": ""}
    ctx["font_settings"] = build_page_font_context(PageFontSetting.Page.SERVICES)
    ctx["page_sections"] = get_page_sections(ctx["services_copy"])

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

    is_mobile = _is_mobile_request(request)
    template_name = "client/mainmenu_mobile.html" if is_mobile else "client/mainmenu.html"
    response = render(request, template_name, ctx)
    response["X-Template-Version"] = "mainmenu-mobile-v5-2026-01-26" if is_mobile else "mainmenu-desktop-v1-2026-01-26"
    return response


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


@staff_member_required
@require_POST
def admin_ui_check_run(request):
    from core.models import ClientUiCheckRun
    from core.services.ui_audit import run_client_ui_check

    run = run_client_ui_check(
        trigger=ClientUiCheckRun.Trigger.MANUAL,
        triggered_by=request.user,
        force=True,
    )

    if not run:
        messages.info(request, "UI check skipped: not due yet.")
        return redirect("admin:index")

    if run.status == ClientUiCheckRun.Status.RUNNING:
        messages.warning(request, "UI check is already running.")
        return redirect("admin:index")

    status_label = run.get_status_display()
    details = f"failures {run.failures_count}, warnings {run.warnings_count}"
    messages.success(request, f"UI check completed: {status_label} ({details}).")
    return redirect("admin:index")


@require_POST
@csrf_exempt
def admin_analytics_collect(request):
    user = request.user
    if not user.is_authenticated or not user.is_staff:
        return JsonResponse({"error": "Staff authentication required."}, status=403)
    return analytics_collect(request)


def admin_staff_usage(request):
    user = request.user
    is_master = user.userrole_set.filter(role__name="Master", user__is_superuser=False).exists()
    if is_master:
        raise PermissionDenied

    page_raw = request.GET.get("page")
    per_page_raw = request.GET.get("per_page")
    try:
        page = int(page_raw or 1)
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(per_page_raw or 50)
    except (TypeError, ValueError):
        per_page = 50

    staff_usage_periods = summarize_staff_usage_periods(windows=[1, 7, 30])
    staff_action_history = summarize_staff_action_history(
        window_days=30,
        page=page,
        per_page=per_page,
    )
    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Staff time tracking",
            "staff_usage_periods": staff_usage_periods,
            "staff_action_history": staff_action_history,
        }
    )
    return TemplateResponse(request, "admin/staff_usage.html", context)


def admin_web_analytics_insights(request):
    user = request.user
    is_master = user.userrole_set.filter(role__name="Master", user__is_superuser=False).exists()
    if is_master:
        raise PermissionDenied

    window_raw = request.GET.get("window") or ""
    try:
        window_days = int(window_raw)
    except (TypeError, ValueError):
        window_days = 30
    window_days = max(1, min(window_days, 90))

    analytics_summary = summarize_web_analytics_insights(
        window_days=window_days,
        host=request.get_host(),
        include_admin=False,
    )

    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Web analytics insights",
            "analytics": analytics_summary,
            "window_days": analytics_summary.get("window_days", window_days),
            "window_options": [1, 7, 30, 60, 90],
        }
    )
    return TemplateResponse(request, "admin/analytics_insights.html", context)


def _summarize_email_logs(queryset):
    summary = queryset.aggregate(
        total=models.Count("id"),
        success=models.Count("id", filter=Q(success=True)),
        failed=models.Count("id", filter=Q(success=False)),
        recipients=models.Sum("recipient_count"),
        last_sent=models.Max("sent_at"),
    )
    total = summary.get("total") or 0
    recipients = summary.get("recipients") or 0
    success = summary.get("success") or 0
    failed = summary.get("failed") or 0
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "recipients": recipients,
        "avg_recipients": round(recipients / total, 1) if total else 0,
        "success_rate": round(success / total * 100, 1) if total else 0,
        "last_sent": summary.get("last_sent"),
    }


def admin_email_overview(request):
    user = request.user
    is_master = user.userrole_set.filter(role__name="Master", user__is_superuser=False).exists()
    if is_master:
        raise PermissionDenied

    today = timezone.localdate()
    base_qs = EmailSendLog.objects.all()

    total_summary = _summarize_email_logs(base_qs)
    last_log = base_qs.order_by("-sent_at").first()

    window_defs = [("Last 24 hours", 1), ("Last 7 days", 7), ("Last 30 days", 30)]
    window_stats = []
    for label, days in window_defs:
        start = today - timedelta(days=days - 1)
        qs = base_qs.filter(sent_at__date__gte=start)
        stats = _summarize_email_logs(qs)
        stats.update({"label": label, "days": days, "start": start})
        window_stats.append(stats)

    top_window_start = today - timedelta(days=29)
    top_rows = list(
        base_qs.filter(sent_at__date__gte=top_window_start)
        .values("email_type")
        .annotate(
            total=models.Count("id"),
            success=models.Count("id", filter=Q(success=True)),
            failed=models.Count("id", filter=Q(success=False)),
            recipients=models.Sum("recipient_count"),
            last_sent=models.Max("sent_at"),
        )
        .order_by("-total")[:10]
    )

    recent_failures = list(base_qs.filter(success=False).order_by("-sent_at")[:12])

    campaign_qs = EmailCampaign.objects.all()
    campaign_summary = campaign_qs.aggregate(
        total=models.Count("id"),
        draft=models.Count("id", filter=Q(status=EmailCampaign.Status.DRAFT)),
        sending=models.Count("id", filter=Q(status=EmailCampaign.Status.SENDING)),
        sent=models.Count("id", filter=Q(status=EmailCampaign.Status.SENT)),
        partial=models.Count("id", filter=Q(status=EmailCampaign.Status.PARTIAL)),
        failed=models.Count("id", filter=Q(status=EmailCampaign.Status.FAILED)),
        sent_total=models.Sum("sent_count"),
        failed_total=models.Sum("failed_count"),
        recipients_total=models.Sum("recipients_total"),
    )
    sent_total = campaign_summary.get("sent_total") or 0
    failed_total = campaign_summary.get("failed_total") or 0
    delivered_total = sent_total + failed_total
    campaign_summary.update(
        {
            "sent_total": sent_total,
            "failed_total": failed_total,
            "recipients_total": campaign_summary.get("recipients_total") or 0,
            "success_rate": round(sent_total / delivered_total * 100, 1) if delivered_total else 0,
        }
    )
    last_campaign = (
        campaign_qs.exclude(send_completed_at__isnull=True)
        .order_by("-send_completed_at")
        .first()
    )

    subscriber_total = EmailSubscriber.objects.count()
    subscriber_active = EmailSubscriber.objects.filter(is_active=True).count()
    subscriber_new = EmailSubscriber.objects.filter(
        created_at__date__gte=today - timedelta(days=29)
    ).count()
    subscriber_summary = {
        "total": subscriber_total,
        "active": subscriber_active,
        "inactive": max(subscriber_total - subscriber_active, 0),
        "new_30": subscriber_new,
    }

    type_inputs = [row["email_type"] for row in top_rows]
    type_inputs += [log.email_type for log in recent_failures]
    if last_log:
        type_inputs.append(last_log.email_type)
    type_meta = describe_email_types(type_inputs)

    top_types = []
    for row in top_rows:
        total = row.get("total") or 0
        success = row.get("success") or 0
        recipients = row.get("recipients") or 0
        top_types.append(
            {
                "email_type": row.get("email_type"),
                "total": total,
                "success": success,
                "failed": row.get("failed") or 0,
                "recipients": recipients,
                "avg_recipients": round(recipients / total, 1) if total else 0,
                "success_rate": round(success / total * 100, 1) if total else 0,
                "last_sent": row.get("last_sent"),
                "reason": type_meta.get(row.get("email_type")),
            }
        )

    failure_rows = [
        {"log": log, "reason": type_meta.get(log.email_type)} for log in recent_failures
    ]

    last_reason = None
    if last_log:
        last_reason = type_meta.get(last_log.email_type, {}).get("label")

    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Email overview",
            "total_summary": total_summary,
            "last_log": last_log,
            "last_reason": last_reason,
            "window_stats": window_stats,
            "top_types": top_types,
            "recent_failures": failure_rows,
            "campaign_summary": campaign_summary,
            "last_campaign": last_campaign,
            "subscriber_summary": subscriber_summary,
        }
    )
    return TemplateResponse(request, "admin/email_overview.html", context)


def admin_email_logs(request):
    user = request.user
    is_master = user.userrole_set.filter(role__name="Master", user__is_superuser=False).exists()
    if is_master:
        raise PermissionDenied

    qs = EmailSendLog.objects.all()
    filters = {
        "q": (request.GET.get("q") or "").strip(),
        "status": (request.GET.get("status") or "").strip(),
        "type": (request.GET.get("type") or "").strip(),
        "start": (request.GET.get("start") or "").strip(),
        "end": (request.GET.get("end") or "").strip(),
    }

    if filters["q"]:
        qs = qs.filter(
            Q(subject__icontains=filters["q"])
            | Q(from_email__icontains=filters["q"])
            | Q(email_type__icontains=filters["q"])
        )

    if filters["type"]:
        qs = qs.filter(email_type=filters["type"])

    if filters["status"] == "success":
        qs = qs.filter(success=True)
    elif filters["status"] == "failed":
        qs = qs.filter(success=False)

    start_date = parse_date(filters["start"]) if filters["start"] else None
    end_date = parse_date(filters["end"]) if filters["end"] else None
    if start_date:
        qs = qs.filter(sent_at__date__gte=start_date)
    if end_date:
        qs = qs.filter(sent_at__date__lte=end_date)

    qs = qs.order_by("-sent_at")
    stats = qs.aggregate(
        total=models.Count("id"),
        success=models.Count("id", filter=Q(success=True)),
        failed=models.Count("id", filter=Q(success=False)),
    )
    total = stats.get("total") or 0
    success = stats.get("success") or 0
    failed = stats.get("failed") or 0

    per_page_raw = request.GET.get("per_page")
    page_raw = request.GET.get("page")
    try:
        per_page = int(per_page_raw or 50)
    except (TypeError, ValueError):
        per_page = 50
    per_page = max(25, min(per_page, 200))
    try:
        page = int(page_raw or 1)
    except (TypeError, ValueError):
        page = 1
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    offset = (page - 1) * per_page
    page_logs = list(qs[offset : offset + per_page])

    type_options = list(
        EmailSendLog.objects.values_list("email_type", flat=True)
        .distinct()
        .order_by("email_type")
    )

    type_meta = describe_email_types([log.email_type for log in page_logs])
    rows = []
    for log in page_logs:
        recipients_preview = ""
        recipients = log.recipients if isinstance(log.recipients, list) else []
        if recipients:
            preview = recipients[:2]
            recipients_preview = ", ".join(preview)
            if len(recipients) > 2:
                recipients_preview += f" +{len(recipients) - 2} more"

        reason = type_meta.get(log.email_type)
        campaign_url = None
        if reason and reason.get("campaign_id"):
            try:
                campaign_url = reverse(
                    "admin:core_emailcampaign_change", args=[reason["campaign_id"]]
                )
            except Exception:
                campaign_url = None

        rows.append(
            {
                "log": log,
                "reason": reason,
                "recipients_preview": recipients_preview,
                "detail_url": reverse("admin:core_emailsendlog_change", args=[log.pk]),
                "campaign_url": campaign_url,
            }
        )

    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Email send logs",
            "filters": filters,
            "logs": rows,
            "stats": {
                "total": total,
                "success": success,
                "failed": failed,
                "success_rate": round(success / total * 100, 1) if total else 0,
            },
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
                "has_previous": page > 1,
                "has_next": page < total_pages,
                "prev_page": page - 1,
                "next_page": page + 1,
            },
            "type_options": type_options,
        }
    )
    return TemplateResponse(request, "admin/email_send_logs.html", context)


def admin_email_history(request):
    user = request.user
    is_master = user.userrole_set.filter(role__name="Master", user__is_superuser=False).exists()
    if is_master:
        raise PermissionDenied

    today = timezone.localdate()
    window_raw = (request.GET.get("window") or "30").strip().lower()
    if window_raw == "all":
        window_days = None
    else:
        try:
            window_days = int(window_raw)
        except (TypeError, ValueError):
            window_days = 30
        window_days = max(1, min(window_days, 365))

    qs = EmailSendLog.objects.all()
    if window_days:
        start_date = today - timedelta(days=window_days - 1)
        qs = qs.filter(sent_at__date__gte=start_date)
    else:
        start_date = None

    summary_rows = list(
        qs.values("email_type")
        .annotate(
            total=models.Count("id"),
            success=models.Count("id", filter=Q(success=True)),
            failed=models.Count("id", filter=Q(success=False)),
            recipients=models.Sum("recipient_count"),
            last_sent=models.Max("sent_at"),
        )
        .order_by("-total")
    )

    overall_total = sum(row.get("total") or 0 for row in summary_rows) or 0
    type_meta = describe_email_types([row["email_type"] for row in summary_rows])
    history_rows = []
    for row in summary_rows:
        total = row.get("total") or 0
        success = row.get("success") or 0
        recipients = row.get("recipients") or 0
        history_rows.append(
            {
                "email_type": row.get("email_type"),
                "total": total,
                "success": success,
                "failed": row.get("failed") or 0,
                "recipients": recipients,
                "avg_recipients": round(recipients / total, 1) if total else 0,
                "success_rate": round(success / total * 100, 1) if total else 0,
                "share": round(total / overall_total * 100, 1) if overall_total else 0,
                "last_sent": row.get("last_sent"),
                "reason": type_meta.get(row.get("email_type")),
            }
        )

    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Email history",
            "window_days": window_days,
            "window_options": [7, 30, 90, 180, 365, "all"],
            "start_date": start_date,
            "history_rows": history_rows,
            "overall_total": overall_total,
        }
    )
    return TemplateResponse(request, "admin/email_history.html", context)


def admin_email_campaign_history(request):
    user = request.user
    is_master = user.userrole_set.filter(role__name="Master", user__is_superuser=False).exists()
    if is_master:
        raise PermissionDenied

    today = timezone.localdate()
    window_raw = (request.GET.get("window") or "90").strip().lower()
    if window_raw == "all":
        window_days = None
    else:
        try:
            window_days = int(window_raw)
        except (TypeError, ValueError):
            window_days = 90
        window_days = max(1, min(window_days, 365))

    status_filter = (request.GET.get("status") or "").strip().lower()

    qs = EmailCampaign.objects.select_related("sent_by")
    if window_days:
        start_date = today - timedelta(days=window_days - 1)
        qs = qs.filter(created_at__date__gte=start_date)
    else:
        start_date = None

    if status_filter:
        qs = qs.filter(status=status_filter)

    qs = qs.order_by("-created_at")
    stats = qs.aggregate(
        total=models.Count("id"),
        sent=models.Count("id", filter=Q(status=EmailCampaign.Status.SENT)),
        partial=models.Count("id", filter=Q(status=EmailCampaign.Status.PARTIAL)),
        failed=models.Count("id", filter=Q(status=EmailCampaign.Status.FAILED)),
        draft=models.Count("id", filter=Q(status=EmailCampaign.Status.DRAFT)),
        sending=models.Count("id", filter=Q(status=EmailCampaign.Status.SENDING)),
        sent_total=models.Sum("sent_count"),
        failed_total=models.Sum("failed_count"),
        recipients_total=models.Sum("recipients_total"),
    )
    sent_total = stats.get("sent_total") or 0
    failed_total = stats.get("failed_total") or 0
    delivered_total = sent_total + failed_total
    stats.update(
        {
            "sent_total": sent_total,
            "failed_total": failed_total,
            "recipients_total": stats.get("recipients_total") or 0,
            "success_rate": round(sent_total / delivered_total * 100, 1) if delivered_total else 0,
        }
    )

    per_page_raw = request.GET.get("per_page")
    page_raw = request.GET.get("page")
    try:
        per_page = int(per_page_raw or 50)
    except (TypeError, ValueError):
        per_page = 50
    per_page = max(25, min(per_page, 200))
    try:
        page = int(page_raw or 1)
    except (TypeError, ValueError):
        page = 1
    total = stats.get("total") or 0
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    offset = (page - 1) * per_page
    campaigns = list(qs[offset : offset + per_page])

    rows = []
    for campaign in campaigns:
        delivered = campaign.sent_count + campaign.failed_count
        success_rate = round(campaign.sent_count / delivered * 100, 1) if delivered else 0
        recipients_url = None
        logs_url = None
        try:
            recipients_url = (
                reverse("admin:core_emailcampaignrecipient_changelist")
                + f"?campaign__id__exact={campaign.id}"
            )
        except Exception:
            recipients_url = None
        try:
            logs_url = reverse("admin-email-logs") + f"?type=campaign:{campaign.id}"
        except Exception:
            logs_url = None
        rows.append(
            {
                "campaign": campaign,
                "success_rate": success_rate,
                "change_url": reverse("admin:core_emailcampaign_change", args=[campaign.id]),
                "recipients_url": recipients_url,
                "logs_url": logs_url,
            }
        )

    window_param = f"window={window_days}" if window_days else "window=all"

    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Email campaign history",
            "window_days": window_days,
            "window_options": [30, 90, 180, 365, "all"],
            "status_filter": status_filter,
            "stats": stats,
            "rows": rows,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
                "has_previous": page > 1,
                "has_next": page < total_pages,
                "prev_page": page - 1,
                "next_page": page + 1,
            },
            "start_date": start_date,
            "window_param": window_param,
        }
    )
    return TemplateResponse(request, "admin/email_campaign_history.html", context)

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
        return HttpResponseBadRequest("service, tech, start_time required")

    service = get_object_or_404(Service, pk=service_id)
    master  = get_object_or_404(CustomUserDisplay, pk=master_id)

    if not get_service_masters(service).filter(pk=master.pk).exists():
        from django.http import HttpResponseBadRequest
        return HttpResponseBadRequest("tech can't perform this service")

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
            return HttpResponseBadRequest("tech can't perform this service")
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
    all_qs = Service.objects.select_related('category')
    qs = all_qs
    if cat:
        qs = qs.filter(category_id=cat)

    ranked = _rank_services(qs, q, limit=60)
    if not ranked and all_qs.exists():
        ranked = _rank_services(all_qs, q, limit=60)

    results = []
    for s in ranked:
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
        ctx["dealer_copy"] = DealerStatusPageCopy.get_solo()
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
    font_settings = build_page_font_context(PageFontSetting.Page.FINANCING)
    financing_copy = FinancingPageCopy.get_solo()
    return render(
        request,
        "financing.html",
        {
            "font_settings": font_settings,
            "financing_copy": financing_copy,
            "header_copy": financing_copy,
        },
    )

def our_story_view(request):
    about_copy = AboutPageCopy.get_solo()
    font_settings = build_page_font_context(PageFontSetting.Page.ABOUT)
    return render(
        request,
        "client/our_story.html",
        {
            "about_copy": about_copy,
            "header_copy": about_copy,
            "font_settings": font_settings,
        },
    )


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

    def _silent_success():
        if is_ajax:
            return JsonResponse({"ok": True, "message": "Check your inbox for your code."})
        messages.success(request, "Thanks! Check your inbox for your code.")
        return HttpResponseRedirect(_lead_redirect_target(request))

    email = (request.POST.get("email") or "").strip()
    if not email and request.content_type and "application/json" in request.content_type:
        try:
            payload = json.loads(request.body.decode("utf-8"))
            email = (payload.get("email") or "").strip()
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            email = ""

    evaluation = evaluate_lead_submission(request, purpose="site_notice", email=email)

    if evaluation.action == "rate_limited":
        log_lead_submission(
            form_type="site_notice",
            evaluation=evaluation,
            outcome="rate_limited",
            success=False,
            validation_errors="rate_limited",
        )
        return _error("Please try again in a few minutes.", status=429)

    if evaluation.honeypot_hit:
        log_lead_submission(
            form_type="site_notice",
            evaluation=evaluation,
            outcome="blocked",
            success=False,
            validation_errors="honeypot",
        )
        queue_lead_digest(
            form_type="site_notice",
            suspicious=True,
            ip_address=evaluation.ip_address,
            asn=evaluation.cf_asn,
        )
        return _silent_success()

    if not evaluation.token_valid:
        log_lead_submission(
            form_type="site_notice",
            evaluation=evaluation,
            outcome="blocked",
            success=False,
            validation_errors=f"token:{evaluation.token_error or 'invalid'}",
        )
        if evaluation.token_error == "too_fast":
            return _error("Please wait a moment and try again.", status=429)
        return _error("Please refresh the page and try again.", status=400)

    if not email:
        log_lead_submission(
            form_type="site_notice",
            evaluation=evaluation,
            outcome="rejected",
            success=False,
            validation_errors="email_missing",
        )
        return _error("Email is required.")

    try:
        validate_email(email)
    except ValidationError:
        log_lead_submission(
            form_type="site_notice",
            evaluation=evaluation,
            outcome="rejected",
            success=False,
            validation_errors="email_invalid",
        )
        return _error("Enter a valid email.")

    if evaluation.action == "blocked":
        log_lead_submission(
            form_type="site_notice",
            evaluation=evaluation,
            outcome="blocked",
            success=False,
            validation_errors="score_block",
        )
        queue_lead_digest(
            form_type="site_notice",
            suspicious=True,
            ip_address=evaluation.ip_address,
            asn=evaluation.cf_asn,
        )
        return _silent_success()

    sender = (
        getattr(settings, "DEFAULT_FROM_EMAIL", None)
        or getattr(settings, "SUPPORT_EMAIL", None)
    )
    if not sender:
        logger.warning("Missing DEFAULT_FROM_EMAIL/SUPPORT_EMAIL for site notice signup.")
        log_lead_submission(
            form_type="site_notice",
            evaluation=evaluation,
            outcome="rejected",
            success=False,
            validation_errors="email_sender_missing",
        )
        return _error("Email service is unavailable.", status=500)

    code = _resolve_site_notice_code()
    brand = email_brand_name()
    context = base_email_context({"brand": brand, "welcome_code": code})
    template = render_email_template("site_notice_welcome", context)
    summary_lines = [f"Welcome code: {code}", "Discount: 5% off"]
    text_body = join_text_sections(
        [template.greeting],
        template.intro_lines,
        summary_lines,
        template.footer_lines,
    )

    try:
        html_body = build_email_html(
            title=template.title,
            preheader=template.preheader,
            greeting=template.greeting,
            intro_lines=template.intro_lines,
            summary_rows=[("Welcome code", code), ("Discount", "5% off")],
            notice_title=template.notice_title or None,
            notice_lines=template.notice_lines,
            footer_lines=template.footer_lines,
            cta_label=template.cta_label,
            cta_url=template.cta_url,
        )
        send_html_email(
            subject=template.subject,
            text_body=text_body,
            html_body=html_body,
            from_email=sender,
            recipient_list=[email],
            email_type="site_notice_welcome",
        )
    except Exception:
        logger.exception("Failed to send site notice code email to %s", email)
        log_lead_submission(
            form_type="site_notice",
            evaluation=evaluation,
            outcome="rejected",
            success=False,
            validation_errors="email_send_failed",
        )
        return _error("Unable to send the code right now.", status=500)

    signup = None
    try:
        signup = SiteNoticeSignup.objects.create(
            email=email,
            welcome_code=code,
            welcome_sent_at=timezone.now(),
        )
    except Exception:
        logger.exception("Failed to record site notice signup for %s", email)

    if signup:
        if evaluation.action == "allow":
            try:
                notify_about_site_notice_signup(signup.pk)
            except Exception:
                logger.exception("Failed to send Telegram alert for site notice signup %s", signup.pk)
        else:
            queue_lead_digest(
                form_type="site_notice",
                suspicious=True,
                ip_address=evaluation.ip_address,
                asn=evaluation.cf_asn,
            )

    try:
        user = CustomUserDisplay.objects.filter(email__iexact=email).first()
        profile = getattr(user, "userprofile", None) if user else None
        if profile:
            profile.set_marketing_consent(True)
            profile.save(update_fields=["email_marketing_consent", "email_marketing_consented_at"])
    except Exception:
        logger.exception("Failed to update marketing consent for %s", email)

    log_lead_submission(
        form_type="site_notice",
        evaluation=evaluation,
        outcome="suspected" if evaluation.action == "suspect" else "accepted",
        success=True,
    )

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
    email = (request.POST.get("email") or "").strip()
    evaluation = evaluate_lead_submission(request, purpose="service_lead", email=email)

    if evaluation.action == "rate_limited":
        log_lead_submission(
            form_type="service_lead",
            evaluation=evaluation,
            outcome="rate_limited",
            success=False,
            validation_errors="rate_limited",
        )
        messages.error(request, "Please try again in a few minutes.")
        return HttpResponseRedirect(_lead_redirect_target(request))

    if evaluation.honeypot_hit:
        log_lead_submission(
            form_type="service_lead",
            evaluation=evaluation,
            outcome="blocked",
            success=False,
            validation_errors="honeypot",
        )
        queue_lead_digest(
            form_type="service_lead",
            suspicious=True,
            ip_address=evaluation.ip_address,
            asn=evaluation.cf_asn,
        )
        messages.success(
            request,
            "Thanks! Your request reached our team. Expect a reply shortly.",
        )
        return HttpResponseRedirect(_lead_redirect_target(request))

    if not evaluation.token_valid:
        log_lead_submission(
            form_type="service_lead",
            evaluation=evaluation,
            outcome="blocked",
            success=False,
            validation_errors=f"token:{evaluation.token_error or 'invalid'}",
        )
        if evaluation.token_error == "too_fast":
            messages.error(request, "Please wait a moment and try again.")
        else:
            messages.error(request, "Please refresh the page and try again.")
        return HttpResponseRedirect(_lead_redirect_target(request))

    if evaluation.action == "blocked":
        log_lead_submission(
            form_type="service_lead",
            evaluation=evaluation,
            outcome="blocked",
            success=False,
            validation_errors="score_block",
        )
        queue_lead_digest(
            form_type="service_lead",
            suspicious=True,
            ip_address=evaluation.ip_address,
            asn=evaluation.cf_asn,
        )
        messages.success(
            request,
            "Thanks! Your request reached our team. Expect a reply shortly.",
        )
        return HttpResponseRedirect(_lead_redirect_target(request))

    form = ServiceLeadForm(request.POST)
    if form.is_valid():
        lead = form.save()
        if evaluation.action == "allow":
            notify_about_service_lead(lead.pk)
        else:
            queue_lead_digest(
                form_type="service_lead",
                suspicious=True,
                ip_address=evaluation.ip_address,
                asn=evaluation.cf_asn,
            )
        log_lead_submission(
            form_type="service_lead",
            evaluation=evaluation,
            outcome="suspected" if evaluation.action == "suspect" else "accepted",
            success=True,
        )
        messages.success(
            request,
            "Thanks! Your request reached our team. Expect a reply shortly.",
        )
        return HttpResponseRedirect(_lead_redirect_target(request))

    errors = [err for field_errors in form.errors.values() for err in field_errors]
    error_msg = "Please correct the highlighted fields and try again."
    if errors:
        error_msg = f"{error_msg} ({'; '.join(errors)})"
    log_lead_submission(
        form_type="service_lead",
        evaluation=evaluation,
        outcome="rejected",
        success=False,
        validation_errors="; ".join(errors),
    )
    messages.error(request, error_msg)
    return HttpResponseRedirect(_lead_redirect_target(request))


def project_journal_view(request):
    tag_filter = (request.GET.get("tag") or "").strip()
    normalized_tag = tag_filter.lower()

    published_posts = list(ProjectJournalEntry.objects.published().prefetch_related("photos"))
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
    gallery_posts = list(visible_posts)

    project_payload = []
    for post in gallery_posts:
        published_label = ""
        if post.published_at:
            published_label = timezone.localtime(post.published_at).strftime("%b %d, %Y")
        before_images = []
        after_images = []
        photos = list(getattr(post, "photos", []).all()) if hasattr(post, "photos") else []
        if photos:
            before_images = [
                {"url": photo.image.url, "alt": photo.alt_text or ""}
                for photo in photos
                if photo.kind == "before" and photo.image
            ]
            after_images = [
                {"url": photo.image.url, "alt": photo.alt_text or ""}
                for photo in photos
                if photo.kind == "after" and photo.image
            ]

        if not before_images:
            before_gallery = post.before_gallery or []
            if isinstance(before_gallery, list):
                before_images = list(before_gallery)
        if not after_images:
            after_gallery = post.after_gallery or []
            if isinstance(after_gallery, list):
                after_images = list(after_gallery)
        if not before_images and post.cover_image:
            before_images = [{"url": post.cover_image.url, "alt": f"{post.title} before"}]
        if not after_images and post.cover_image:
            after_images = [{"url": post.cover_image.url, "alt": f"{post.title} after"}]
        project_payload.append(
            {
                "id": str(post.pk),
                "slug": post.slug,
                "title": post.title,
                "hero_title": post.hero_title,
                "excerpt": post.excerpt or "",
                "overview": post.overview or "",
                "parts": post.parts or "",
                "customizations": post.customizations or "",
                "backstory": post.backstory or "",
                "body": post.body or "",
                "result_highlight": post.result_highlight or "",
                "client_name": post.client_name or "",
                "location": post.location or "",
                "reading_time": post.reading_time or 0,
                "published_label": published_label,
                "before_images": before_images,
                "after_images": after_images,
                "cover_image": post.cover_image.url if post.cover_image else "",
                "services": post.services_list,
                "tags": post.tag_list,
            }
        )

    context = {
        "featured_post": featured_post,
        "journal_posts": remaining_posts,
        "gallery_posts": gallery_posts,
        "project_payload": project_payload,
        "available_tags": available_tags,
        "tag_filter": tag_filter,
        "has_posts": bool(visible_posts),
        "page_title": "Project Journal",
        "meta_description": "Quiet corner of Bad Guy Motors where we document completed builds, wraps, and custom work.",
        "font_settings": build_page_font_context(PageFontSetting.Page.PROJECT_JOURNAL),
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
