from __future__ import annotations

import json
import secrets
from typing import Any

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.services.shop_sync import (
    append_shop_lead,
    replace_shop_payload,
    serialize_shop_record,
    shop_shared_data_key,
    get_or_create_shop_record,
)


def _shop_api_allowed_origin(origin: str) -> str:
    allowed_origins = getattr(settings, "SHOP_API_ALLOWED_ORIGINS", []) or []
    origin = (origin or "").strip()
    if not origin or not allowed_origins:
        return ""
    if "*" in allowed_origins:
        return origin
    return origin if origin in allowed_origins else ""


def _add_cors_headers(response, request):
    allowed_origin = _shop_api_allowed_origin(request.headers.get("Origin", ""))
    if allowed_origin:
        response["Access-Control-Allow-Origin"] = allowed_origin
        response["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response["Access-Control-Allow-Methods"] = "GET, PUT, POST, OPTIONS"
        response["Access-Control-Allow-Credentials"] = "true"
        response["Vary"] = "Origin"
    return response


def _options_response(request):
    return _add_cors_headers(HttpResponse(status=204), request)


def _shop_auth_token(request) -> str:
    auth_header = (request.headers.get("Authorization", "") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return (
        (request.headers.get("X-Shop-Api-Token", "") or "").strip()
        or (request.GET.get("token", "") or "").strip()
    )


def _unauthorized_response(request):
    return _add_cors_headers(JsonResponse({"detail": "Unauthorized"}, status=401), request)


def _require_shop_auth(request):
    expected = (getattr(settings, "SHOP_API_TOKEN", "") or "").strip()
    if not expected:
        return JsonResponse({"detail": "SHOP_API_TOKEN is not configured"}, status=503)
    provided = _shop_auth_token(request)
    if not provided or not secrets.compare_digest(provided, expected):
        return _unauthorized_response(request)
    return None


def _parse_json_body(request) -> Any:
    if not request.body:
        return {}
    return json.loads(request.body.decode("utf-8"))


@csrf_exempt
@require_http_methods(["GET", "PUT", "OPTIONS"])
def shop_shared_data_api(request, key: str):
    if request.method == "OPTIONS":
        return _options_response(request)

    auth_error = _require_shop_auth(request)
    if auth_error is not None:
        return _add_cors_headers(auth_error, request)

    if key != shop_shared_data_key():
        return _add_cors_headers(JsonResponse({"detail": "Unknown storage key"}, status=404), request)

    if request.method == "GET":
        record = get_or_create_shop_record()
        return _add_cors_headers(JsonResponse(serialize_shop_record(record)), request)

    try:
        payload = _parse_json_body(request)
    except json.JSONDecodeError:
        return _add_cors_headers(JsonResponse({"detail": "Invalid JSON body"}, status=400), request)

    if isinstance(payload, dict) and "value" in payload:
        value = payload.get("value")
        shared = bool(payload.get("shared", True))
    else:
        value = payload
        shared = True

    if not isinstance(value, dict):
        return _add_cors_headers(JsonResponse({"detail": "Payload must be a JSON object"}, status=400), request)

    record = replace_shop_payload(value, shared=shared)
    return _add_cors_headers(JsonResponse(serialize_shop_record(record)), request)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def shop_website_lead_webhook(request):
    if request.method == "OPTIONS":
        return _options_response(request)

    auth_error = _require_shop_auth(request)
    if auth_error is not None:
        return _add_cors_headers(auth_error, request)

    try:
        payload = _parse_json_body(request)
    except json.JSONDecodeError:
        return _add_cors_headers(JsonResponse({"detail": "Invalid JSON body"}, status=400), request)

    if not isinstance(payload, dict):
        return _add_cors_headers(JsonResponse({"detail": "Payload must be a JSON object"}, status=400), request)

    missing = [field for field in ("name", "contact", "product") if not str(payload.get(field, "")).strip()]
    if missing:
        return _add_cors_headers(
            JsonResponse({"detail": f"Missing required fields: {', '.join(missing)}"}, status=400),
            request,
        )

    record, lead = append_shop_lead(payload)
    return _add_cors_headers(
        JsonResponse(
            {
                "ok": True,
                "lead": lead,
                "document": serialize_shop_record(record),
            }
        ),
        request,
    )
