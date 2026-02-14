# core/views.py
import logging
import re
from decimal import Decimal, InvalidOperation

from django.apps import apps
from django import forms
from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.db import models
from django.db.models import Prefetch, Q
from django.contrib import admin, messages
from django.contrib.admin.models import ADDITION, CHANGE, DELETION
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
from django.core.paginator import Paginator
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
from django.template.response import TemplateResponse
from datetime import date, datetime, timedelta
import json
import html as py_html
from django.utils.functional import cached_property
from PIL import Image, UnidentifiedImageError

from core.email_templates import base_email_context, email_brand_name, join_text_sections, render_email_template
from core.emails import build_email_html, send_html_email
from core.models import (
    Appointment,
    AdminSidebarSeen,
    ServiceCategory,
    Service,
    CustomUserDisplay,
    AppointmentStatusHistory,
    LegalPage,
    ProjectJournalCategory,
    ProjectJournalEntry,
    ProjectJournalPageCopy,
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
    DealerApplication,
    DealerStatusPageCopy,
    DealerTier,
    EmailCampaign,
    EmailSendLog,
    EmailSubscriber,
    ClientFile,
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
from core.services.ip_location import format_ip_location, get_client_ip
from core.services.email_reporting import describe_email_types
from core.services.dealer_application_emails import send_dealer_application_submitted
from notifications.services import (
    notify_about_service_lead,
    notify_about_site_notice_signup,
    notify_about_dealer_application,
    queue_lead_digest,
)
from core.utils import format_currency
from store.models import Product as StoreProduct, StoreShippingSettings

logger = logging.getLogger(__name__)
BOOKING_REFERENCE_IMAGE_MAX_MB = int(getattr(settings, "BOOKING_REFERENCE_IMAGE_MAX_MB", 8))
BOOKING_REFERENCE_IMAGE_MAX_BYTES = BOOKING_REFERENCE_IMAGE_MAX_MB * 1024 * 1024


def _validate_booking_reference_image(uploaded_file) -> str:
    if not uploaded_file:
        return ""
    if uploaded_file.size > BOOKING_REFERENCE_IMAGE_MAX_BYTES:
        return f"Image is too large. Limit: {BOOKING_REFERENCE_IMAGE_MAX_MB} MB."
    content_type = (uploaded_file.content_type or "").lower()
    if content_type and not content_type.startswith("image/"):
        return "Please upload an image file."
    try:
        with Image.open(uploaded_file) as img:
            img.verify()
        uploaded_file.seek(0)
    except (UnidentifiedImageError, OSError):
        return "Unsupported image. Use JPG, PNG, or WEBP."
    return ""


def _store_booking_reference_file(*, owner, uploaded_file, service_name: str, start_dt):
    if not owner or not uploaded_file:
        return None
    when_label = ""
    try:
        when_label = timezone.localtime(start_dt).strftime("%Y-%m-%d %H:%M")
    except Exception:
        when_label = ""
    description = f"Appointment reference for {service_name}"
    if when_label:
        description += f" ({when_label})"
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    try:
        return ClientFile.objects.create(
            user=owner,
            file=uploaded_file,
            uploaded_by=ClientFile.USER,
            description=description[:255],
        )
    except Exception:
        logger.exception("Failed to store appointment reference file for user=%s", getattr(owner, "pk", None))
    return None


@require_http_methods(["GET", "POST"])
@csrf_protect
def admin_logout(request):
    logout(request)
    return redirect(getattr(settings, "LOGOUT_REDIRECT_URL", "/"))


@staff_member_required
@require_POST
@csrf_protect
def admin_notifications_read_all(request):
    """
    Marks all admin sidebar notification items as seen for the current staff user.
    This powers the "Read all" action in the admin notification center (bell menu).
    """
    user = request.user
    now = timezone.now()

    config = getattr(settings, "ADMIN_SIDEBAR_SECTIONS", None) or settings.JAZZMIN_SETTINGS.get(
        "custom_sidebar", []
    ) or []
    pairs: set[tuple[str, str]] = set()
    for section in config:
        for group in section.get("groups", []):
            if group.get("notifications_enabled") is False:
                continue
            for item in group.get("items", []):
                if item.get("notifications_enabled") is False:
                    continue
                model_label = (item.get("model") or "").strip()
                if not model_label:
                    continue
                try:
                    app_label, model_name = model_label.split(".", 1)
                    model = apps.get_model(app_label, model_name)
                except Exception:
                    continue
                pairs.add((model._meta.app_label, model._meta.model_name))

    for app_label, model_name in pairs:
        AdminSidebarSeen.objects.update_or_create(
            user=user,
            app_label=app_label,
            model_name=model_name,
            defaults={"last_seen_at": now},
        )

    next_url = (request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("admin:index") or "").strip()
    if not next_url or not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse("admin:index")
    return HttpResponseRedirect(next_url)


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
        ServiceCategory.objects
        .annotate(services_count=models.Count("service", distinct=True))
        .order_by("-services_count", "name")
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
@require_GET
def admin_client_search(request):
    """
    Lightweight search endpoint for the calendar "quick add" modal.
    Returns a small list of matching clients (id + label + meta).
    """
    query = (request.GET.get("q") or "").strip()
    if len(query) < 2:
        return JsonResponse({"results": []})

    # Prefer client role, but fall back to non-staff users if roles aren't configured.
    from core.models import Role
    client_role = Role.objects.filter(name__iexact="Client").first()

    qs = CustomUserDisplay.objects.select_related("userprofile").all()
    if client_role:
        qs = qs.filter(Q(is_staff=False) | Q(userrole__role=client_role)).distinct()
    else:
        qs = qs.filter(is_staff=False)

    tokens = query.split()
    if len(tokens) >= 2:
        a, b = tokens[0], tokens[1]
        name_q = (
            Q(first_name__icontains=a, last_name__icontains=b) |
            Q(first_name__icontains=b, last_name__icontains=a)
        )
    else:
        name_q = Q(first_name__icontains=query) | Q(last_name__icontains=query)

    qs = (
        qs.filter(
            name_q |
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(userprofile__phone__icontains=query)
        )
        .order_by("first_name", "last_name", "username")[:15]
    )

    results = []
    for user in qs:
        profile = getattr(user, "userprofile", None)
        label = user.get_full_name() or user.username or user.email or str(user.id)
        results.append({
            "id": user.id,
            "label": label,
            "email": user.email or "",
            "phone": getattr(profile, "phone", "") if profile else "",
        })
    return JsonResponse({"results": results})


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

    user_raw = (request.GET.get("user") or "").strip()
    action_raw = (request.GET.get("action") or "").strip().lower()
    model_raw = (request.GET.get("model") or "").strip()
    q = (request.GET.get("q") or "").strip()
    start_raw = (request.GET.get("start") or "").strip()
    end_raw = (request.GET.get("end") or "").strip()

    user_id = None
    if user_raw:
        try:
            user_id = int(user_raw)
        except (TypeError, ValueError):
            user_id = None

    action_map = {
        "1": ADDITION,
        "add": ADDITION,
        "added": ADDITION,
        "addition": ADDITION,
        "2": CHANGE,
        "change": CHANGE,
        "changed": CHANGE,
        "3": DELETION,
        "delete": DELETION,
        "deleted": DELETION,
        "deletion": DELETION,
    }
    action_flag = action_map.get(action_raw) if action_raw else None
    action_choice = ""
    if action_flag == ADDITION:
        action_choice = "added"
    elif action_flag == CHANGE:
        action_choice = "changed"
    elif action_flag == DELETION:
        action_choice = "deleted"

    content_type_id = None
    if model_raw:
        try:
            content_type_id = int(model_raw)
        except (TypeError, ValueError):
            content_type_id = None

    # Default to last 30 days unless a date range is provided.
    window_days = 30
    start_date = parse_date(start_raw) if start_raw else None
    end_date = parse_date(end_raw) if end_raw else None
    today = timezone.localdate()
    if not start_date and not end_date:
        end_date = today
        start_date = today - timedelta(days=window_days - 1)
    else:
        if start_date and not end_date:
            end_date = start_date
        if end_date and not start_date:
            start_date = end_date
        if start_date and end_date and end_date < start_date:
            start_date, end_date = end_date, start_date
        if start_date and end_date and (end_date - start_date).days > 364:
            start_date = end_date - timedelta(days=364)

    staff_usage_periods = summarize_staff_usage_periods(windows=[1, 7, 30])
    staff_action_history = summarize_staff_action_history(
        window_days=window_days,
        page=page,
        per_page=per_page,
        user_id=user_id,
        action_flag=action_flag,
        content_type_id=content_type_id,
        start_date=start_date,
        end_date=end_date,
        query=q,
    )

    staff_users = list(
        CustomUserDisplay.objects.filter(is_staff=True)
        .order_by("first_name", "last_name", "username", "email")
        .only("id", "first_name", "last_name", "username", "email", "is_active")
    )
    staff_user_options = []
    for staff_user in staff_users:
        label = (
            (staff_user.get_full_name() or "").strip()
            or (staff_user.username or "").strip()
            or (staff_user.email or "").strip()
            or f"User {staff_user.pk}"
        )
        staff_user_options.append(
            {
                "id": staff_user.pk,
                "label": label,
                "email": (staff_user.email or "").strip(),
                "is_active": bool(staff_user.is_active),
            }
        )

    filter_state = {
        "user": str(user_id) if user_id else "",
        "action": action_choice,
        "model": str(content_type_id) if content_type_id else "",
        "q": q,
        "start": start_date.isoformat() if start_date else "",
        "end": end_date.isoformat() if end_date else "",
    }

    def _qs(**overrides) -> str:
        from urllib.parse import urlencode

        params = {k: v for k, v in filter_state.items() if v}
        params["per_page"] = str(per_page)
        params.update({k: str(v) for k, v in overrides.items() if v is not None and v != ""})
        encoded = urlencode(params)
        return f"?{encoded}" if encoded else ""
    staff_action_links = {
        "per_page_25": _qs(per_page=25, page=1),
        "per_page_50": _qs(per_page=50, page=1),
        "prev": _qs(page=staff_action_history.get("prev_page") or 1) if staff_action_history.get("has_previous") else "",
        "next": _qs(page=staff_action_history.get("next_page") or 1) if staff_action_history.get("has_next") else "",
        "reset": reverse("admin-staff-usage"),
    }

    for row in staff_action_history.get("totals_by_user", []) or []:
        row["filter_url"] = _qs(user=row.get("user_id"), page=1)

    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Staff time tracking",
            "staff_usage_periods": staff_usage_periods,
            "staff_action_history": staff_action_history,
            "staff_action_filters": filter_state,
            "staff_action_staff_options": staff_user_options,
            "staff_action_links": staff_action_links,
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


class MerchEconomicsSettingsForm(forms.Form):
    free_shipping_threshold_cad = forms.DecimalField(
        label="Free shipping threshold (Canada, CAD)",
        required=False,
        min_value=0,
        decimal_places=2,
        max_digits=10,
        help_text="Shown to customers on the merch + checkout pages. Leave blank (or 0) to disable.",
        widget=forms.NumberInput(attrs={"step": "0.01", "placeholder": "e.g. 150.00"}),
    )
    delivery_cost_under_threshold_cad = forms.DecimalField(
        label="Delivery cost under threshold (Canada, CAD)",
        required=False,
        min_value=0,
        decimal_places=2,
        max_digits=10,
        help_text="Charged in checkout when shipping to Canada and the cart subtotal is below the free shipping threshold. Leave blank (or 0) to disable.",
        widget=forms.NumberInput(attrs={"step": "0.01", "placeholder": "e.g. 25.00"}),
    )


def admin_merch_economics(request):
    user = request.user
    is_master = user.userrole_set.filter(role__name="Master", user__is_superuser=False).exists()
    if is_master:
        raise PermissionDenied
    if not user.has_perm("store.view_product"):
        raise PermissionDenied

    # Filters
    q = (request.GET.get("q") or "").strip()
    missing_cost = (request.GET.get("missing_cost") or "").strip() in {"1", "true", "yes", "on"}
    show_inactive = (request.GET.get("inactive") or "").strip() in {"1", "true", "yes", "on"}

    # Shipping settings
    settings_obj = StoreShippingSettings.load()
    initial_threshold = getattr(settings_obj, "free_shipping_threshold_cad", None) if settings_obj else None
    initial_delivery_cost = getattr(settings_obj, "delivery_cost_under_threshold_cad", None) if settings_obj else None
    shipping_form = MerchEconomicsSettingsForm(
        request.POST or None,
        initial={
            "free_shipping_threshold_cad": initial_threshold,
            "delivery_cost_under_threshold_cad": initial_delivery_cost,
        },
    )

    if request.method == "POST":
        if not user.has_perm("store.change_storeshippingsettings"):
            raise PermissionDenied
        if shipping_form.is_valid():
            threshold = shipping_form.cleaned_data.get("free_shipping_threshold_cad")
            delivery_cost = shipping_form.cleaned_data.get("delivery_cost_under_threshold_cad")
            if threshold is not None:
                try:
                    threshold = Decimal(str(threshold))
                except (InvalidOperation, TypeError, ValueError):
                    threshold = None
            if threshold is not None and threshold <= 0:
                threshold = None
            if delivery_cost is not None:
                try:
                    delivery_cost = Decimal(str(delivery_cost))
                except (InvalidOperation, TypeError, ValueError):
                    delivery_cost = None
            if delivery_cost is not None and delivery_cost <= 0:
                delivery_cost = None

            if settings_obj:
                settings_obj.free_shipping_threshold_cad = threshold
                settings_obj.delivery_cost_under_threshold_cad = delivery_cost
                settings_obj.save(
                    update_fields=[
                        "free_shipping_threshold_cad",
                        "delivery_cost_under_threshold_cad",
                        "updated_at",
                    ]
                )
            else:
                StoreShippingSettings.objects.create(
                    free_shipping_threshold_cad=threshold,
                    delivery_cost_under_threshold_cad=delivery_cost,
                )

            try:
                from django.core.cache import cache

                cache.delete("bgm:store_shipping:v1")
            except Exception:
                pass

            messages.success(request, "Saved merch shipping settings.")
            return redirect(reverse("admin-merch-economics"))

    merch_qs = StoreProduct.objects.select_related("category").all()
    merch_qs = merch_qs.filter(
        Q(category__slug="merch")
        | Q(sku__startswith="PF-")
        | Q(slug__startswith="merch-")
    )
    if not show_inactive:
        merch_qs = merch_qs.filter(is_active=True)
    if q:
        merch_qs = merch_qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    if missing_cost:
        merch_qs = merch_qs.filter(unit_cost__isnull=True)

    merch_products = list(merch_qs.order_by("name", "sku"))

    rows = []
    margin_values = []
    for product in merch_products:
        price = None
        try:
            price = product.display_price
        except Exception:
            price = None
        cost = getattr(product, "unit_cost", None)

        profit = None
        margin_pct = None
        if price is not None and cost is not None:
            try:
                price_val = Decimal(price)
                cost_val = Decimal(cost)
            except (InvalidOperation, TypeError, ValueError):
                price_val = None
                cost_val = None
            if price_val is not None and price_val > 0:
                profit = (price_val - cost_val).quantize(Decimal("0.01"))
                margin_pct = float(((profit / price_val) * Decimal("100")).quantize(Decimal("0.1")))
                margin_values.append(margin_pct)

        rows.append(
            {
                "id": product.id,
                "name": product.name,
                "sku": product.sku,
                "is_active": bool(product.is_active),
                "category": getattr(getattr(product, "category", None), "display_name", "") or "",
                "price_label": format_currency(price) if price is not None else "—",
                "cost_label": format_currency(cost) if cost is not None else "—",
                "profit_label": format_currency(profit) if profit is not None else "—",
                "margin_pct": margin_pct,
                "change_url": reverse("admin:store_product_change", args=[product.id]),
                "public_url": product.get_absolute_url() if hasattr(product, "get_absolute_url") else "",
            }
        )

    threshold = StoreShippingSettings.get_free_shipping_threshold_cad()
    delivery_cost = StoreShippingSettings.get_delivery_cost_under_threshold_cad()
    summary = {
        "count": len(merch_products),
        "active_count": sum(1 for p in merch_products if p.is_active),
        "missing_cost_count": sum(1 for p in merch_products if getattr(p, "unit_cost", None) is None),
        "avg_margin_pct": round(sum(margin_values) / len(margin_values), 1) if margin_values else None,
        "threshold_label": format_currency(threshold) if threshold else "",
        "delivery_cost_label": format_currency(delivery_cost) if delivery_cost else "",
    }

    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Merch economics",
            "q": q,
            "missing_cost": missing_cost,
            "show_inactive": show_inactive,
            "shipping_form": shipping_form,
            "summary": summary,
            "rows": rows,
        }
    )
    return TemplateResponse(request, "admin/merch_economics.html", context)


def _summarize_email_logs(queryset):
    summary = queryset.aggregate(
        total=models.Count("id"),
        success_count=models.Count("id", filter=Q(success=True)),
        failed_count=models.Count("id", filter=Q(success=False)),
        recipients=models.Sum("recipient_count"),
        last_sent=models.Max("sent_at"),
    )
    total = summary.get("total") or 0
    recipients = summary.get("recipients") or 0
    success = summary.get("success_count") or 0
    failed = summary.get("failed_count") or 0
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
            success_count=models.Count("id", filter=Q(success=True)),
            failed_count=models.Count("id", filter=Q(success=False)),
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
        success = row.get("success_count") or 0
        recipients = row.get("recipients") or 0
        top_types.append(
            {
                "email_type": row.get("email_type"),
                "total": total,
                "success": success,
                "failed": row.get("failed_count") or 0,
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
        success_count=models.Count("id", filter=Q(success=True)),
        failed_count=models.Count("id", filter=Q(success=False)),
    )
    total = stats.get("total") or 0
    success = stats.get("success_count") or 0
    failed = stats.get("failed_count") or 0

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
            success_count=models.Count("id", filter=Q(success=True)),
            failed_count=models.Count("id", filter=Q(success=False)),
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
        success = row.get("success_count") or 0
        recipients = row.get("recipients") or 0
        history_rows.append(
            {
                "email_type": row.get("email_type"),
                "total": total,
                "success": success,
                "failed": row.get("failed_count") or 0,
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
    content_type = (request.content_type or "").lower()
    is_json = "application/json" in content_type
    payload = {}
    if is_json:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except Exception:
            from django.http import HttpResponseBadRequest
            return HttpResponseBadRequest("invalid json")
    else:
        payload = request.POST

    service_id = payload.get("service")
    master_id = payload.get("master")
    start_iso = payload.get("start_time")

    if not service_id or not start_iso:
        return HttpResponseBadRequest("service and start_time required")

    service = get_object_or_404(Service, pk=service_id)

    try:
        start_dt = parse_datetime(start_iso) or _tz_aware(datetime.fromisoformat(start_iso))
        if not timezone.is_aware(start_dt):
            start_dt = _tz_aware(start_dt)
    except Exception:
        from django.http import HttpResponseBadRequest
        return HttpResponseBadRequest("invalid start_time")

    master = None
    if master_id:
        master = get_object_or_404(CustomUserDisplay, pk=master_id)
        if not get_service_masters(service).filter(pk=master.pk).exists():
            from django.http import HttpResponseBadRequest
            return HttpResponseBadRequest("tech can't perform this service")
    else:
        # Mobile flow can submit without a staff id; pick any staff member
        # who is currently free at the requested start time.
        local_start = timezone.localtime(start_dt).replace(second=0, microsecond=0)
        probe_day = _tz_aware(datetime(local_start.year, local_start.month, local_start.day, 12, 0))
        slots_map = get_available_slots(service, probe_day, master=None)
        service_masters = list(get_service_masters(service))

        for candidate in service_masters:
            slots = slots_map.get(candidate.id, [])
            matched = any(
                timezone.localtime(slot).replace(second=0, microsecond=0) == local_start
                for slot in slots
            )
            if matched:
                master = candidate
                break

        if not master:
            return JsonResponse({"error": "No staff is available for the selected time."}, status=400)

    if is_json:
        contact = payload.get("contact") or {}
        contact_name = (contact.get("name") or "").strip()
        contact_email = (contact.get("email") or "").strip()
        raw_phone = (contact.get("phone") or "").strip()
    else:
        contact_name = (
            payload.get("contact_name")
            or payload.get("name")
            or payload.get("contact")
            or ""
        ).strip()
        contact_email = (
            payload.get("contact_email")
            or payload.get("email")
            or ""
        ).strip()
        raw_phone = (
            payload.get("contact_phone")
            or payload.get("phone")
            or ""
        ).strip()

    reference_file = request.FILES.get("reference_image")
    if reference_file:
        reference_error = _validate_booking_reference_image(reference_file)
        if reference_error:
            return JsonResponse({"errors": {"reference_image": reference_error}}, status=400)

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

    file_owner = user
    if not file_owner and contact_email:
        file_owner = CustomUserDisplay.objects.filter(email__iexact=contact_email).first()
    if reference_file and file_owner:
        _store_booking_reference_file(
            owner=file_owner,
            uploaded_file=reference_file,
            service_name=service.name,
            start_dt=appt.start_time,
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

    try:
        from sorl.thumbnail import get_thumbnail  # type: ignore
    except Exception:  # pragma: no cover
        get_thumbnail = None

    results = []
    for s in ranked:
        disc = s.get_active_discount() if not s.contact_for_estimate else None
        base_price = str(s.base_price_amount())
        price = None
        if not s.contact_for_estimate:
            price = str(s.get_discounted_price()) if disc else base_price

        image_url = ""
        if getattr(s, "image", None):
            if get_thumbnail is not None:
                try:
                    image_url = get_thumbnail(s.image, "320", quality=72, format="WEBP").url
                except Exception:
                    image_url = ""
            if not image_url:
                try:
                    image_url = s.image.url
                except Exception:
                    image_url = ""

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
            "image": image_url,
        })
    return JsonResponse({"results": results})

from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import TemplateView

from core.forms_dealer import (
    DealerApplyAddressForm,
    DealerApplyBusinessForm,
    DealerApplyReferencesForm,
    DealerApplySignatureForm,
)
from core.models import DealerApplication, DealerTier, DealerTierLevel
from core.services.dealer_portal import build_portal_snapshot


DEALER_WIZARD_SESSION_KEY = "dealer_apply_wizard_v1"
DEALER_WIZARD_STEPS: list[tuple[str, type[forms.Form], str]] = [
    ("business", DealerApplyBusinessForm, "Business"),
    ("address", DealerApplyAddressForm, "Address"),
    ("references", DealerApplyReferencesForm, "References"),
    ("signature", DealerApplySignatureForm, "Signature"),
]


def _dealer_wizard_state(session) -> dict:
    raw = session.get(DEALER_WIZARD_SESSION_KEY)
    if isinstance(raw, dict):
        return raw
    return {}


def _dealer_wizard_next_step(state: dict) -> str:
    for slug, _form, _label in DEALER_WIZARD_STEPS:
        if not state.get(slug):
            return slug
    return DEALER_WIZARD_STEPS[-1][0]


def _dealer_application_for_user(user):
    try:
        return user.dealer_application
    except DealerApplication.DoesNotExist:
        return None
    except Exception:
        return None


class DealerEntryView(View):
    """
    Single entrypoint for the topbar "Dealers" link.

    - Anonymous users: sent to login/registration with a clear intent message.
    - Approved dealers: land on the dealer portal.
    - Logged-in non-dealers: taken through the multi-step dealer application wizard.
    """

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            tier_levels = DealerTierLevel.objects.filter(is_active=True).order_by(
                "minimum_spend",
                "sort_order",
                "code",
            )
            return render(
                request,
                "core/dealer/entry_public.html",
                {"tier_levels": tier_levels},
            )

        profile = getattr(request.user, "userprofile", None)
        if profile and profile.is_dealer:
            return redirect("dealer-status")

        dealer_app = _dealer_application_for_user(request.user)
        if dealer_app and dealer_app.status != DealerApplication.Status.REJECTED:
            return redirect("dealer-status")

        state = _dealer_wizard_state(request.session)
        next_step = _dealer_wizard_next_step(state)
        return redirect("dealer-apply-step", step=next_step)


class DealerApplyWizardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dealer/apply_wizard.html"

    def dispatch(self, request, *args, **kwargs):
        profile = getattr(request.user, "userprofile", None)
        if profile and profile.is_dealer:
            return redirect("dealer-status")

        dealer_app = _dealer_application_for_user(request.user)
        if dealer_app and dealer_app.status != DealerApplication.Status.REJECTED:
            return redirect("dealer-status")

        step = kwargs.get("step") or DEALER_WIZARD_STEPS[0][0]
        step_slugs = {slug for slug, _form, _label in DEALER_WIZARD_STEPS}
        if step not in step_slugs:
            return redirect("dealer-apply-step", step=DEALER_WIZARD_STEPS[0][0])

        state = _dealer_wizard_state(request.session)
        allowed_slug = _dealer_wizard_next_step(state)
        step_order = [slug for slug, _form, _label in DEALER_WIZARD_STEPS]
        if step_order.index(step) > step_order.index(allowed_slug):
            return redirect("dealer-apply-step", step=allowed_slug)

        self.step_slug = step
        return super().dispatch(request, *args, **kwargs)

    def _step_meta(self):
        for idx, (slug, form_cls, label) in enumerate(DEALER_WIZARD_STEPS):
            if slug == self.step_slug:
                return idx, form_cls, label
        return 0, DEALER_WIZARD_STEPS[0][1], DEALER_WIZARD_STEPS[0][2]

    def _initial_for_step(self, *, step_slug: str):
        state = _dealer_wizard_state(self.request.session)
        initial = dict(state.get(step_slug) or {})

        # Prefill from an existing rejected application (re-apply flow).
        dealer_app = _dealer_application_for_user(self.request.user)
        if dealer_app and dealer_app.status == DealerApplication.Status.REJECTED:
            for field in (
                "business_name",
                "operating_as",
                "phone",
                "email",
                "website",
                "years_in_business",
                "business_type",
                "preferred_tier",
                "business_address",
                "city",
                "province",
                "postal_code",
                "gst_tax_id",
                "business_license_number",
                "resale_certificate_number",
                "reference_1_name",
                "reference_1_phone",
                "reference_1_email",
                "reference_2_name",
                "reference_2_phone",
                "reference_2_email",
                "authorized_signature_printed_name",
                "authorized_signature_title",
                "authorized_signature_date",
            ):
                if field not in initial:
                    val = getattr(dealer_app, field, None)
                    if val not in (None, ""):
                        initial[field] = val

        profile = getattr(self.request.user, "userprofile", None)
        if step_slug == "business":
            initial.setdefault("email", getattr(self.request.user, "email", "") or "")
            if profile and getattr(profile, "phone", None):
                initial.setdefault("phone", profile.phone)
            if not initial.get("preferred_tier"):
                initial["preferred_tier"] = DealerTier.TIER_5

        if step_slug == "address":
            if profile and getattr(profile, "address", None):
                initial.setdefault("business_address", profile.address)

        if step_slug == "signature":
            printed_name = (
                (self.request.user.get_full_name() or "").strip()
                or (getattr(self.request.user, "username", "") or "").strip()
            )
            if printed_name:
                initial.setdefault("authorized_signature_printed_name", printed_name)

        return initial

    def _store_step_data(self, *, step_slug: str, cleaned: dict) -> None:
        state = _dealer_wizard_state(self.request.session)
        safe = {}
        for key, value in (cleaned or {}).items():
            if isinstance(value, (date, datetime)):
                safe[key] = value.isoformat()
            else:
                safe[key] = value
        state[step_slug] = safe
        self.request.session[DEALER_WIZARD_SESSION_KEY] = state
        self.request.session.modified = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        idx, _form_cls, label = self._step_meta()
        ctx["step_slug"] = self.step_slug
        ctx["step_label"] = label
        ctx["step_index"] = idx + 1
        ctx["step_total"] = len(DEALER_WIZARD_STEPS)
        ctx["steps"] = [
            {"slug": slug, "label": step_label, "index": i + 1}
            for i, (slug, _f, step_label) in enumerate(DEALER_WIZARD_STEPS)
        ]
        ctx["progress_percent"] = int(((idx + 1) / max(1, len(DEALER_WIZARD_STEPS))) * 100)
        ctx["prev_step"] = DEALER_WIZARD_STEPS[idx - 1][0] if idx > 0 else None
        ctx["next_step"] = DEALER_WIZARD_STEPS[idx + 1][0] if (idx + 1) < len(DEALER_WIZARD_STEPS) else None
        try:
            ctx["tier_levels"] = list(
                DealerTierLevel.objects.filter(is_active=True).order_by(
                    "minimum_spend", "sort_order", "code"
                )
            )
        except Exception:
            ctx["tier_levels"] = []
        return ctx

    def get(self, request, *args, **kwargs):
        _idx, form_cls, _label = self._step_meta()
        form = form_cls(initial=self._initial_for_step(step_slug=self.step_slug))
        ctx = self.get_context_data(**kwargs)
        ctx["form"] = form
        return self.render_to_response(ctx)

    def post(self, request, *args, **kwargs):
        idx, form_cls, _label = self._step_meta()
        form = form_cls(data=request.POST)
        ctx = self.get_context_data(**kwargs)
        if not form.is_valid():
            ctx["form"] = form
            return self.render_to_response(ctx)

        self._store_step_data(step_slug=self.step_slug, cleaned=form.cleaned_data)

        is_last = (idx + 1) >= len(DEALER_WIZARD_STEPS)
        if not is_last:
            next_slug = DEALER_WIZARD_STEPS[idx + 1][0]
            return redirect("dealer-apply-step", step=next_slug)

        # --- submit ---
        state = _dealer_wizard_state(request.session)
        payload = {}
        for slug, _form, _label in DEALER_WIZARD_STEPS:
            payload.update(state.get(slug) or {})

        preferred = payload.get("preferred_tier") or DealerTier.TIER_5
        # Bump created_at on submit so admin notifications (which track created_at for public submissions)
        # reflect fresh (re)submissions as "new" work items.
        submitted_at = timezone.now()
        defaults = {
            "business_name": payload.get("business_name", "").strip(),
            "operating_as": payload.get("operating_as", "").strip(),
            "phone": payload.get("phone", "").strip(),
            "email": payload.get("email", "").strip(),
            "website": payload.get("website", "").strip(),
            "years_in_business": payload.get("years_in_business") or None,
            "business_type": payload.get("business_type", "").strip(),
            "preferred_tier": preferred,
            "business_address": payload.get("business_address", "").strip(),
            "city": payload.get("city", "").strip(),
            "province": payload.get("province", "").strip(),
            "postal_code": payload.get("postal_code", "").strip(),
            "gst_tax_id": payload.get("gst_tax_id", "").strip(),
            "business_license_number": payload.get("business_license_number", "").strip(),
            "resale_certificate_number": payload.get("resale_certificate_number", "").strip(),
            "reference_1_name": payload.get("reference_1_name", "").strip(),
            "reference_1_phone": payload.get("reference_1_phone", "").strip(),
            "reference_1_email": payload.get("reference_1_email", "").strip(),
            "reference_2_name": payload.get("reference_2_name", "").strip(),
            "reference_2_phone": payload.get("reference_2_phone", "").strip(),
            "reference_2_email": payload.get("reference_2_email", "").strip(),
            "authorized_signature_printed_name": payload.get("authorized_signature_printed_name", "").strip(),
            "authorized_signature_title": payload.get("authorized_signature_title", "").strip(),
            "authorized_signature_date": (
                parse_date(payload.get("authorized_signature_date"))
                if isinstance(payload.get("authorized_signature_date"), str)
                else (payload.get("authorized_signature_date") or None)
            ),
            "status": DealerApplication.Status.PENDING,
            "assigned_tier": "",
            "internal_note": "",
            "reviewed_at": None,
            "reviewed_by": None,
            "created_at": submitted_at,
        }

        with transaction.atomic():
            app, _created = DealerApplication.objects.update_or_create(
                user=request.user,
                defaults=defaults,
            )
            def _notify():
                try:
                    notify_about_dealer_application(app.pk)
                except Exception:
                    logger.exception("Failed to send Telegram alert for dealer application %s", app.pk)
                try:
                    send_dealer_application_submitted(app.pk)
                except Exception:
                    logger.exception("Failed to send dealer application email for %s", app.pk)
            transaction.on_commit(_notify)

        request.session.pop(DEALER_WIZARD_SESSION_KEY, None)
        request.session.modified = True
        return redirect(f"{reverse('dealer-status')}?submitted=1")


class DealerStatusView(LoginRequiredMixin, TemplateView):
    template_name = "core/dealer/status.html"

    def get_contextDataBase(self, **kwargs):
        # оставлено намеренно неверным именем метода; используйте get_context_data ниже
        pass

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        up = getattr(self.request.user, "userprofile", None)
        dealer_app = _dealer_application_for_user(self.request.user)
        ctx["dealer_copy"] = DealerStatusPageCopy.get_solo()
        ctx["userprofile"] = up
        ctx["dealer_application"] = dealer_app
        ctx["submitted"] = str(self.request.GET.get("submitted") or "").strip() in {"1", "true", "yes"}

        # Keep profile flags consistent with application status, but avoid revoking
        # wholesale access just because a record is "pending" (e.g. dealer resubmitted info).
        if dealer_app and up:
            if (
                dealer_app.status == DealerApplication.Status.REJECTED
                and getattr(up, "is_dealer", False)
            ):
                up.is_dealer = False
                up.dealer_tier = DealerTier.NONE
                update_fields = ["is_dealer", "dealer_tier"]
                if hasattr(up, "dealer_welcome_seen"):
                    up.dealer_welcome_seen = True
                    update_fields.append("dealer_welcome_seen")
                up.save(update_fields=update_fields)

            # Auto-heal: if we have a historical activation timestamp but access was
            # accidentally flipped off, restore access on the dealer status page.
            if (
                dealer_app.status == DealerApplication.Status.PENDING
                and (not getattr(up, "is_dealer", False))
                and getattr(up, "dealer_since", None)
            ):
                update_fields = []
                up.is_dealer = True
                update_fields.append("is_dealer")

                final_tier = dealer_app.resolved_tier()
                if final_tier and final_tier != DealerTier.NONE and up.dealer_tier != final_tier:
                    up.dealer_tier = final_tier
                    update_fields.append("dealer_tier")

                if hasattr(up, "dealer_welcome_seen") and not up.dealer_welcome_seen:
                    up.dealer_welcome_seen = True
                    update_fields.append("dealer_welcome_seen")

                if update_fields:
                    up.save(update_fields=update_fields)

        # Backfill: if an application is marked approved but the profile was not upgraded
        # (e.g. staff changed status in admin form), upgrade the profile here so the dealer
        # portal behaves correctly.
        if (
            dealer_app
            and dealer_app.status == DealerApplication.Status.APPROVED
            and up
            and (not up.is_dealer)
            # If dealer_since is already set, assume staff intentionally revoked access by
            # unchecking is_dealer. Do not auto-reinstate on page load.
            and (not up.dealer_since)
        ):
            update_fields = []
            became_dealer = False

            if not up.is_dealer:
                up.is_dealer = True
                became_dealer = True
                update_fields.append("is_dealer")

            final_tier = dealer_app.resolved_tier()
            if final_tier and final_tier != DealerTier.NONE and up.dealer_tier != final_tier:
                up.dealer_tier = final_tier
                update_fields.append("dealer_tier")

            if not up.dealer_since:
                up.dealer_since = dealer_app.reviewed_at or timezone.now()
                update_fields.append("dealer_since")

            if became_dealer and hasattr(up, "dealer_welcome_seen"):
                up.dealer_welcome_seen = False
                update_fields.append("dealer_welcome_seen")

            if update_fields:
                up.save(update_fields=update_fields)

        # Keep dealer pricing in sync with the staff-assigned tier.
        # If staff explicitly set assigned_tier, treat it as authoritative (even if
        # it's lower than the current profile tier). This avoids mismatches where the
        # portal/catalog show a different discount than what ops configured in admin.
        if (
            dealer_app
            and up
            and getattr(up, "is_dealer", False)
            and dealer_app.status == DealerApplication.Status.APPROVED
        ):
            assigned_tier = str(getattr(dealer_app, "assigned_tier", "") or "").strip()
            if assigned_tier and assigned_tier != getattr(up, "dealer_tier", ""):
                update_fields = ["dealer_tier"]
                up.dealer_tier = assigned_tier
                if not getattr(up, "dealer_since", None):
                    up.dealer_since = dealer_app.reviewed_at or timezone.now()
                    update_fields.append("dealer_since")
                up.save(update_fields=update_fields)

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

        is_dealer = portal_snapshot.get("is_dealer", False)
        ctx["is_dealer"] = is_dealer

        # UI-only tier/discount display. For non-dealers, show the requested tier's
        # configured discount percent (without enabling wholesale pricing).
        tier_levels = ctx.get("tier_levels") or []
        tier_map = {getattr(t, "code", None): t for t in tier_levels if getattr(t, "code", None)}

        portal_display = {
            "tier_code": portal_snapshot.get("tier_code"),
            "tier_label": portal_snapshot.get("tier_label"),
            "discount_percent": portal_snapshot.get("discount_percent") or 0,
            "note": "",
        }
        if (not is_dealer) and dealer_app:
            requested_code = dealer_app.resolved_tier() or dealer_app.preferred_tier or DealerTier.NONE
            requested_level = tier_map.get(requested_code)
            if requested_level:
                portal_display.update(
                    {
                        "tier_code": requested_code,
                        "tier_label": requested_level.label,
                        "discount_percent": requested_level.discount_percent or 0,
                        "note": "after approval",
                    }
                )
        ctx["portal_display"] = portal_display

        if dealer_app:
            application_code = dealer_app.resolved_tier() or dealer_app.preferred_tier or DealerTier.NONE
            application_level = tier_map.get(application_code)
            if application_level:
                ctx["application_tier_label"] = application_level.label
                ctx["application_tier_discount_percent"] = application_level.discount_percent or 0
            else:
                ctx["application_tier_label"] = dealer_app.get_preferred_tier_display() or application_code
                ctx["application_tier_discount_percent"] = 0

        # One-time success banner: show once after approval, then mark as seen.
        show_welcome = bool(is_dealer and up and hasattr(up, "dealer_welcome_seen") and not up.dealer_welcome_seen)
        ctx["show_dealer_welcome"] = show_welcome
        if show_welcome:
            ctx["dealer_welcome_callout"] = ctx["dealer_copy"].dealer_welcome_callout
            up.dealer_welcome_seen = True
            up.save(update_fields=["dealer_welcome_seen"])

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


@require_GET
def project_journal_view(request):
    def _normalize_gallery(raw):
        items = []
        if not isinstance(raw, list):
            return items
        for entry in raw:
            if isinstance(entry, dict):
                url = (entry.get("url") or "").strip()
                alt = (entry.get("alt") or "").strip()
            else:
                url = str(entry or "").strip()
                alt = ""
            if not url:
                continue
            items.append({"url": url, "alt": alt})
        return items

    q = (request.GET.get("q") or "").strip()
    sort = (request.GET.get("sort") or "featured").strip().lower()
    project_journal_copy = ProjectJournalPageCopy.get_solo()
    category_slugs = list(request.GET.getlist("cat"))
    if not category_slugs:
        raw = (request.GET.get("cat") or "").strip()
        if raw and "," in raw:
            category_slugs = [seg.strip() for seg in raw.split(",") if seg.strip()]

    qs = (
        ProjectJournalEntry.objects.published()
        .prefetch_related("photos", "categories")
    )

    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(excerpt__icontains=q)
            | Q(tags__icontains=q)
            | Q(overview__icontains=q)
            | Q(parts__icontains=q)
            | Q(customizations__icontains=q)
            | Q(backstory__icontains=q)
            | Q(body__icontains=q)
        )

    if category_slugs:
        qs = qs.filter(categories__slug__in=category_slugs).distinct()

    if sort == "newest":
        qs = qs.order_by("-published_at", "-created_at")
    else:
        # Default: "featured" behavior, still shows everything.
        qs = qs.order_by("-featured", "-published_at", "-created_at")

    paginator = Paginator(qs, 8)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    posts = list(page_obj.object_list)
    for post in posts:
        photos = list(getattr(post, "photos", []).all()) if hasattr(post, "photos") else []
        before_photos = [p for p in photos if p.kind == "before" and getattr(p, "image", None)]
        process_photos = [p for p in photos if p.kind == "process" and getattr(p, "image", None)]
        after_photos = [p for p in photos if p.kind == "after" and getattr(p, "image", None)]

        legacy_before = _normalize_gallery(getattr(post, "before_gallery", None) or [])
        legacy_after = _normalize_gallery(getattr(post, "after_gallery", None) or [])

        post.before_photos = before_photos
        post.process_photos = process_photos
        post.after_photos = after_photos
        post.legacy_before = legacy_before
        post.legacy_after = legacy_after

    available_categories = list(
        ProjectJournalCategory.objects.filter(is_active=True).order_by("sort_order", "name")
    )

    def _build_url(**overrides):
        params = request.GET.copy()
        for key, value in overrides.items():
            if value is None:
                params.pop(key, None)
            else:
                params[key] = str(value)
        return f"{reverse('project-journal')}?{params.urlencode()}" if params else reverse("project-journal")

    next_page_url = ""
    next_page_fragment_url = ""
    if page_obj.has_next():
        next_page_url = _build_url(page=page_obj.next_page_number())
        next_page_fragment_url = _build_url(page=page_obj.next_page_number(), fragment=1)

    filters_min_build_count = max(int(getattr(project_journal_copy, "filters_min_build_count", 10) or 0), 0)
    has_active_filter = bool(q or category_slugs or sort == "newest")
    show_filters = page_obj.paginator.count >= filters_min_build_count or has_active_filter

    context = {
        "posts": posts,
        "page_obj": page_obj,
        "project_journal_copy": project_journal_copy,
        "available_categories": available_categories,
        "active_categories": category_slugs,
        "show_filters": show_filters,
        "q": q,
        "sort": sort,
        "has_posts": bool(posts),
        "next_page_url": next_page_url,
        "next_page_fragment_url": next_page_fragment_url,
        "page_title": (project_journal_copy.page_title or "").strip() or "Builds",
        "meta_description": (
            (project_journal_copy.meta_description or "").strip()
            or "Before-and-after build highlights from Bad Guy Motors. Fast scans, clean comparisons, zero fluff."
        ),
        "font_settings": build_page_font_context(PageFontSetting.Page.PROJECT_JOURNAL),
    }

    if request.GET.get("fragment") == "1":
        return render(request, "client/project_journal_feed_items.html", context)

    return render(request, "client/project_journal.html", context)


@require_GET
def project_journal_post_view(request, slug: str):
    def _normalize_gallery(raw):
        items = []
        if not isinstance(raw, list):
            return items
        for entry in raw:
            if isinstance(entry, dict):
                url = (entry.get("url") or "").strip()
                alt = (entry.get("alt") or "").strip()
            else:
                url = str(entry or "").strip()
                alt = ""
            if not url:
                continue
            items.append({"url": url, "alt": alt})
        return items

    post = get_object_or_404(
        ProjectJournalEntry.objects.published().prefetch_related("photos", "categories"),
        slug=slug,
    )

    photos = list(getattr(post, "photos", []).all()) if hasattr(post, "photos") else []
    before_photos = [p for p in photos if p.kind == "before" and getattr(p, "image", None)]
    process_photos = [p for p in photos if p.kind == "process" and getattr(p, "image", None)]
    after_photos = [p for p in photos if p.kind == "after" and getattr(p, "image", None)]

    legacy_before = _normalize_gallery(getattr(post, "before_gallery", None) or [])
    legacy_after = _normalize_gallery(getattr(post, "after_gallery", None) or [])

    post.before_photos = before_photos
    post.process_photos = process_photos
    post.after_photos = after_photos
    post.legacy_before = legacy_before
    post.legacy_after = legacy_after

    og_image = ""
    if after_photos and after_photos[0].image:
        og_image = after_photos[0].image.url
    elif before_photos and before_photos[0].image:
        og_image = before_photos[0].image.url
    elif post.cover_image:
        og_image = post.cover_image.url
    elif legacy_after:
        og_image = legacy_after[0]["url"]
    elif legacy_before:
        og_image = legacy_before[0]["url"]

    meta_title = f"{post.title} | Bad Guy Motors"
    meta_description = (post.excerpt or post.result_highlight or "Before/after build highlight from Bad Guy Motors.").strip()
    context = {
        "post": post,
        "page_title": post.title,
        "meta_title": meta_title,
        "meta_description": meta_description,
        "meta_section": "builds",
        "meta_image": og_image,
        "font_settings": build_page_font_context(PageFontSetting.Page.PROJECT_JOURNAL),
    }
    return render(request, "client/project_journal_post.html", context)


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
                "ip_address": get_client_ip(request.META),
                "ip_location": format_ip_location(request.META),
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
from django.db.models import Sum, Count, F, Avg
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

    # 6. Средняя оценка клиентов (только опубликованные/одобренные отзывы)
    avg_rating = (
        ClientReview.objects.filter(status=ClientReview.Status.APPROVED)
        .aggregate(avg=Avg("rating"))
        .get("avg")
    )

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
