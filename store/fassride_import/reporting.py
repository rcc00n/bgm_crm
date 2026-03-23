from __future__ import annotations

import json
from typing import Any

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage


def save_json_report(path: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    return default_storage.save(path, ContentFile(encoded))
