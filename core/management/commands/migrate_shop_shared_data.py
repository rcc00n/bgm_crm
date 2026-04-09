from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services.shop_sync import (
    default_shop_payload,
    get_or_create_shop_record,
    normalize_shop_payload,
    replace_shop_payload,
)


class Command(BaseCommand):
    help = (
        "Import the live bgm-shop-data-v3 JSON from the legacy storage layer or a local export "
        "into the Postgres-backed shop shared-data record."
    )

    def add_arguments(self, parser):
        parser.add_argument("--input-file", dest="input_file", help="Path to a JSON export file.")
        parser.add_argument("--legacy-url", dest="legacy_url", help="Legacy storage endpoint URL.")
        parser.add_argument("--legacy-token", dest="legacy_token", help="Legacy storage auth token.")
        parser.add_argument(
            "--auth-header",
            dest="auth_header",
            default=getattr(settings, "SHOP_LEGACY_STORAGE_AUTH_HEADER", "Authorization"),
            help="Header name used for the legacy token. Defaults to Authorization.",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Replace an already-populated Postgres record. Without this flag the command aborts.",
        )

    def handle(self, *args, **options):
        input_file = (options.get("input_file") or "").strip()
        legacy_url = (options.get("legacy_url") or getattr(settings, "SHOP_LEGACY_STORAGE_URL", "") or "").strip()
        legacy_token = (options.get("legacy_token") or getattr(settings, "SHOP_LEGACY_STORAGE_TOKEN", "") or "").strip()
        auth_header = (options.get("auth_header") or "Authorization").strip()
        overwrite = bool(options.get("overwrite"))

        payload = self._load_payload(
            input_file=input_file,
            legacy_url=legacy_url,
            legacy_token=legacy_token,
            auth_header=auth_header,
        )

        record = get_or_create_shop_record()
        current_payload = normalize_shop_payload(record.payload)
        if not overwrite and current_payload != default_shop_payload():
            raise CommandError(
                "The Postgres shop shared-data record already contains data. "
                "Re-run with --overwrite to replace it."
            )

        record = replace_shop_payload(payload, shared=True)
        leads_count = len(record.payload.get("leads") or [])
        jobs_count = len(record.payload.get("jobs") or [])
        designs_count = len(record.payload.get("designs") or [])
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported shop shared data into {record.key} "
                f"(jobs={jobs_count}, leads={leads_count}, designs={designs_count})."
            )
        )

    def _load_payload(
        self,
        *,
        input_file: str,
        legacy_url: str,
        legacy_token: str,
        auth_header: str,
    ):
        if input_file:
            return self._load_file_payload(input_file)
        if legacy_url:
            return self._load_remote_payload(legacy_url=legacy_url, legacy_token=legacy_token, auth_header=auth_header)
        raise CommandError("Provide --input-file or --legacy-url (or configure SHOP_LEGACY_STORAGE_URL).")

    def _load_file_payload(self, input_file: str):
        path = Path(input_file).expanduser()
        if not path.exists():
            raise CommandError(f"Input file not found: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON in {path}: {exc}") from exc
        return self._extract_payload(raw)

    def _load_remote_payload(self, *, legacy_url: str, legacy_token: str, auth_header: str):
        headers = {
            "Accept": "application/json",
        }
        if legacy_token:
            header_value = legacy_token
            if auth_header.lower() == "authorization" and " " not in header_value:
                header_value = f"Bearer {header_value}"
            headers[auth_header] = header_value
        request = Request(legacy_url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=10) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise CommandError(f"Failed to fetch legacy storage payload: {exc}") from exc
        return self._extract_payload(raw)

    def _extract_payload(self, raw):
        if isinstance(raw, dict) and isinstance(raw.get("value"), dict):
            raw = raw["value"]
        if not isinstance(raw, dict):
            raise CommandError("Legacy payload must be a JSON object.")
        return normalize_shop_payload(raw)
