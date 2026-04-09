from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import Lead, ServiceLead, ShopSharedDataRecord
from store.models import CustomFitmentRequest, Order

logger = logging.getLogger(__name__)

DEFAULT_PRODUCT_NAME = "Custom Build"
SHOP_PIPELINE_STAGE = "New Lead"
SHOP_SOURCE = "Website"
SHOP_ALLOWED_PRODUCT_NAMES = (
    "Outlaw Bumper",
    "Badland Bars / Rock Sliders",
    "Mudflaps",
    "Running Boards",
    "Flat Deck",
    "Custom Build",
)


def shop_shared_data_key() -> str:
    return (getattr(settings, "SHOP_SHARED_DATA_KEY", "") or "bgm-shop-data-v3").strip()


def default_shop_payload() -> dict[str, Any]:
    return {
        "jobs": [],
        "leads": [],
        "designs": [],
    }


def normalize_shop_payload(payload: Any) -> dict[str, Any]:
    base = default_shop_payload()
    if isinstance(payload, dict):
        normalized = dict(payload)
    else:
        normalized = {}

    for key, default_value in base.items():
        value = normalized.get(key, default_value)
        normalized[key] = value if isinstance(value, list) else list(default_value)
    return normalized


def serialize_shop_record(record: ShopSharedDataRecord) -> dict[str, Any]:
    return {
        "key": record.key,
        "shared": bool(record.shared),
        "value": normalize_shop_payload(record.payload),
        "updated_at": timezone.localtime(record.updated_at).isoformat() if record.updated_at else "",
    }


def _record_queryset(*, select_for_update: bool = False):
    qs = ShopSharedDataRecord.objects
    if select_for_update:
        qs = qs.select_for_update()
    return qs


def get_or_create_shop_record(*, select_for_update: bool = False) -> ShopSharedDataRecord:
    record, created = _record_queryset(select_for_update=select_for_update).get_or_create(
        key=shop_shared_data_key(),
        defaults={
            "shared": True,
            "payload": default_shop_payload(),
        },
    )
    needs_save = created is False and record.shared is not True
    normalized = normalize_shop_payload(record.payload)
    if normalized != record.payload:
        record.payload = normalized
        needs_save = True
    if needs_save:
        record.shared = True
        record.save(update_fields=["shared", "payload", "updated_at"])
    return record


def replace_shop_payload(payload: Any, *, shared: bool = True) -> ShopSharedDataRecord:
    normalized = normalize_shop_payload(payload)
    with transaction.atomic():
        record = get_or_create_shop_record(select_for_update=True)
        record.shared = bool(shared)
        record.payload = normalized
        record.save(update_fields=["shared", "payload", "updated_at"])
    return record


def _next_lead_id(existing_leads: list[dict[str, Any]]) -> int:
    candidate = int(timezone.now().timestamp() * 1000)
    seen_ids = {
        lead.get("id")
        for lead in existing_leads
        if isinstance(lead, dict)
    }
    while candidate in seen_ids:
        candidate += 1
    return candidate


def _money_to_number(value: Any) -> float:
    try:
        decimal_value = Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError):
        decimal_value = Decimal("0")
    return float(decimal_value.quantize(Decimal("0.01")))


def map_shop_product_name(raw_name: str) -> str:
    name = " ".join(str(raw_name or "").split())
    if not name:
        return DEFAULT_PRODUCT_NAME
    if name in SHOP_ALLOWED_PRODUCT_NAMES:
        return name

    lower_name = name.lower()
    rules = (
        (("outlaw", "bumper"), "Outlaw Bumper"),
        (("outlaw",), "Outlaw Bumper"),
        (("badland",), "Badland Bars / Rock Sliders"),
        (("rock slider",), "Badland Bars / Rock Sliders"),
        (("rock sliders",), "Badland Bars / Rock Sliders"),
        (("mudflap",), "Mudflaps"),
        (("running board",), "Running Boards"),
        (("running boards",), "Running Boards"),
        (("flat deck",), "Flat Deck"),
    )
    for tokens, mapped_name in rules:
        if all(token in lower_name for token in tokens):
            return mapped_name
    return DEFAULT_PRODUCT_NAME


def _pick_primary_order_product(order: Order) -> str:
    mapped_names: list[str] = []
    for item in order.items.select_related("product", "option").all():
        product = getattr(item, "product", None)
        if not product:
            continue
        mapped_names.append(map_shop_product_name(getattr(product, "name", "")))
    unique_names = list(dict.fromkeys(name for name in mapped_names if name))
    if len(unique_names) == 1:
        return unique_names[0]
    if len(unique_names) > 1:
        return DEFAULT_PRODUCT_NAME
    return DEFAULT_PRODUCT_NAME


def _join_note_lines(lines: list[str]) -> str:
    return "\n".join(line for line in lines if line)


def _build_order_notes(order: Order) -> str:
    item_lines: list[str] = []
    for item in order.items.select_related("product", "option").all():
        product = getattr(item, "product", None)
        if not product:
            continue
        label = getattr(product, "name", DEFAULT_PRODUCT_NAME)
        option = getattr(item, "option", None)
        if option and getattr(option, "name", ""):
            label = f"{label} ({option.name})"
        item_lines.append(f"- {label}")

    vehicle_label = " ".join(
        str(part)
        for part in [
            getattr(order, "vehicle_year", None) or "",
            getattr(order, "vehicle_make", "") or "",
            getattr(order, "vehicle_model", "") or "",
        ]
        if str(part).strip()
    ).strip()

    notes = [
        f"Website order #{order.pk}",
        f"Delivery: {getattr(order, 'delivery_method', '') or 'shipping'}",
    ]
    if vehicle_label:
        notes.append(f"Vehicle: {vehicle_label}")
    if item_lines:
        notes.append("Items:")
        notes.extend(item_lines)
    if getattr(order, "notes", ""):
        notes.append(f"Order notes: {order.notes}")
    return _join_note_lines(notes)


def build_shop_lead(
    *,
    name: str,
    contact: str,
    product: str,
    value: Any = 0,
    notes: str = "",
    source: str = SHOP_SOURCE,
    stage: str = SHOP_PIPELINE_STAGE,
    lead_id: int | None = None,
    existing_leads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    existing = existing_leads or []
    return {
        "id": int(lead_id or _next_lead_id(existing)),
        "stage": stage or SHOP_PIPELINE_STAGE,
        "name": " ".join(str(name or "").split()) or "Website Lead",
        "contact": " ".join(str(contact or "").split()),
        "product": map_shop_product_name(product),
        "value": _money_to_number(value),
        "source": source or SHOP_SOURCE,
        "notes": str(notes or "").strip(),
    }


def append_shop_lead(lead_payload: dict[str, Any]) -> tuple[ShopSharedDataRecord, dict[str, Any]]:
    with transaction.atomic():
        record = get_or_create_shop_record(select_for_update=True)
        normalized = normalize_shop_payload(record.payload)
        leads = list(normalized.get("leads") or [])
        lead = build_shop_lead(
            name=lead_payload.get("name", ""),
            contact=lead_payload.get("contact", ""),
            product=lead_payload.get("product", DEFAULT_PRODUCT_NAME),
            value=lead_payload.get("value", 0),
            notes=lead_payload.get("notes", ""),
            source=lead_payload.get("source", SHOP_SOURCE),
            stage=lead_payload.get("stage", SHOP_PIPELINE_STAGE),
            lead_id=lead_payload.get("id"),
            existing_leads=leads,
        )
        leads.append(lead)
        normalized["leads"] = leads
        record.payload = normalized
        record.shared = True
        record.save(update_fields=["shared", "payload", "updated_at"])
    return record, lead


def sync_order_to_shop(order_id: int) -> dict[str, Any]:
    order = Order.objects.prefetch_related("items__product", "items__option").get(pk=order_id)
    total_value = (
        Decimal(str(getattr(order, "payment_amount", 0) or 0))
        + Decimal(str(getattr(order, "payment_balance_due", 0) or 0))
    )
    if total_value <= 0:
        total_value = order.total
    _, lead = append_shop_lead(
        {
            "name": order.customer_name,
            "contact": order.phone or order.email,
            "product": _pick_primary_order_product(order),
            "value": total_value,
            "notes": _build_order_notes(order),
        }
    )
    return lead


def sync_fitment_request_to_shop(request_id: int) -> dict[str, Any]:
    fitment_request = CustomFitmentRequest.objects.select_related("product").get(pk=request_id)
    notes = _join_note_lines(
        [
            "Website fitment request",
            f"Vehicle: {fitment_request.vehicle}" if fitment_request.vehicle else "",
            f"Submodel: {fitment_request.submodel}" if fitment_request.submodel else "",
            f"Goals: {fitment_request.performance_goals}" if fitment_request.performance_goals else "",
            f"Budget: {fitment_request.budget}" if fitment_request.budget else "",
            f"Timeline: {fitment_request.timeline}" if fitment_request.timeline else "",
            f"Notes: {fitment_request.message}" if fitment_request.message else "",
            f"Source URL: {fitment_request.source_url}" if fitment_request.source_url else "",
        ]
    )
    _, lead = append_shop_lead(
        {
            "name": fitment_request.customer_name,
            "contact": fitment_request.phone or fitment_request.email,
            "product": fitment_request.product_name or DEFAULT_PRODUCT_NAME,
            "value": 0,
            "notes": notes,
        }
    )
    return lead


def sync_qualify_lead_to_shop(lead_id: int) -> dict[str, Any]:
    lead_obj = Lead.objects.get(pk=lead_id)
    work_needed = ", ".join(lead_obj.get_work_needed_display_list())
    notes = _join_note_lines(
        [
            "Website qualification lead",
            f"Vehicle: {lead_obj.truck_year} {lead_obj.truck_make} {lead_obj.truck_model}",
            f"Preferred contact: {lead_obj.get_contact_pref_display()}",
            f"Mileage: {lead_obj.get_mileage_display()}",
            f"Primary use: {lead_obj.get_industry_display()}",
            f"Work needed: {work_needed}" if work_needed else "",
            f"Timeline: {lead_obj.get_timeline_display()}",
            f"Biggest frustration: {lead_obj.frustration}" if lead_obj.frustration else "",
        ]
    )
    _, lead = append_shop_lead(
        {
            "name": lead_obj.name,
            "contact": lead_obj.phone or lead_obj.email,
            "product": DEFAULT_PRODUCT_NAME,
            "value": 0,
            "notes": notes,
        }
    )
    return lead


def sync_service_lead_to_shop(lead_id: int) -> dict[str, Any]:
    lead_obj = ServiceLead.objects.get(pk=lead_id)
    notes = _join_note_lines(
        [
            "Website service lead",
            f"Vehicle: {lead_obj.vehicle}" if lead_obj.vehicle else "",
            f"Service needed: {lead_obj.service_needed}",
            f"Notes: {lead_obj.notes}" if lead_obj.notes else "",
            f"Source page: {lead_obj.get_source_page_display()}",
            f"Source URL: {lead_obj.source_url}" if lead_obj.source_url else "",
        ]
    )
    _, lead = append_shop_lead(
        {
            "name": lead_obj.full_name,
            "contact": lead_obj.phone or lead_obj.email,
            "product": DEFAULT_PRODUCT_NAME,
            "value": 0,
            "notes": notes,
        }
    )
    return lead


def queue_shop_sync(sync_func, *args, label: str = "shop sync", **kwargs) -> None:
    def _runner():
        try:
            sync_func(*args, **kwargs)
        except Exception:
            logger.exception("Failed %s", label)

    transaction.on_commit(_runner)
