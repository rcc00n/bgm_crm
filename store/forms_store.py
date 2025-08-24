from __future__ import annotations

from django import forms
from typing import Any
import json
import re

from .models import (
    Product,
    Order,
    Category,
    CarMake,
    CarModel,
)

# =========================
# Admin: Specifications as text
# =========================

_PLACEHOLDER = (
    "diameter: 76 mm\n"
    "material: stainless steel\n"
    "fit: BMW E92 335i, BMW E90 335i\n"
    "weight: 4.3 kg\n"
)

def _smart_value(s: str) -> Any:
    """
    Try to coerce string into list/number/bool/json when it looks like it.
    """
    s = s.strip()
    if not s:
        return ""
    # JSON-shaped
    if s.startswith("{") or s.startswith("[") or (s.startswith('"') and s.endswith('"')):
        try:
            return json.loads(s)
        except Exception:
            pass
    # boolean
    low = s.lower()
    if low in {"true", "false"}:
        return low == "true"
    # number
    try:
        if re.fullmatch(r"-?\d+", s):
            return int(s)
        if re.fullmatch(r"-?\d+\.\d+", s):
            return float(s)
    except Exception:
        pass
    # comma-separated list
    if "," in s:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        if len(parts) > 1:
            return parts
    return s

def parse_specs_text(text: str) -> dict[str, Any]:
    """
    Parse simple 'key: value' lines (comments start with '#').
    """
    data: dict[str, Any] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            # skip malformed lines silently
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = _smart_value(val)
        if key:
            data[key] = val
    return data

def dump_specs_text(specs: dict[str, Any]) -> str:
    """
    Make a user-friendly text from dict for initial display in admin.
    """
    if not specs:
        return ""
    lines: list[str] = []
    for k, v in specs.items():
        if isinstance(v, (list, tuple)):
            vv = ", ".join(str(x) for x in v)
        elif isinstance(v, dict):
            vv = json.dumps(v, ensure_ascii=False)
        else:
            vv = str(v)
        lines.append(f"{k}: {vv}")
    return "\n".join(lines)


class ProductAdminForm(forms.ModelForm):
    """
    Admin-facing form: edit 'specs' via multiline text, not raw JSON.
    """
    specs_text = forms.CharField(
        label="Specifications (text)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 7, "placeholder": _PLACEHOLDER}),
        help_text="One per line as 'key: value'. Use commas for lists or JSON for nested values.",
    )

    class Meta:
        model = Product
        exclude = ("specs",)  # JSON field is maintained under the hood

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.specs:
            self.fields["specs_text"].initial = dump_specs_text(self.instance.specs)

    def clean(self):
        cleaned = super().clean()
        text = cleaned.get("specs_text", "")
        # update underlying JSON field from human-readable text
        self.instance.specs = parse_specs_text(text)
        return cleaned


# =========================
# Catalog filters (Storefront)
# =========================

class ProductFilterForm(forms.Form):
    category = forms.ModelChoiceField(
        label="Category",
        queryset=Category.objects.all(),
        required=False,
        empty_label="All categories",
    )
    make = forms.ModelChoiceField(
        label="Make",
        queryset=CarMake.objects.all().order_by("name"),
        required=False,
        empty_label="Any make",
    )
    model = forms.ModelChoiceField(
        label="Model",
        queryset=CarModel.objects.none(),
        required=False,
        empty_label="Any model",
    )
    year = forms.IntegerField(
        label="Year",
        required=False,
        min_value=1950,
        max_value=2100,
    )

    def __init__(self, *args, **kwargs):
        """
        If a make is selected, narrow 'model' queryset accordingly.
        Otherwise show all models (sorted by make then name).
        """
        super().__init__(*args, **kwargs)
        data = self.data if self.is_bound else self.initial
        make_id = data.get("make")

        if make_id:
            try:
                # handle both str/int ids
                make_id = int(make_id)
            except (TypeError, ValueError):
                pass
            self.fields["model"].queryset = CarModel.objects.filter(make_id=make_id).order_by("name")
        else:
            self.fields["model"].queryset = CarModel.objects.all().order_by("make__name", "name")


# =========================
# Checkout form (Order)
# =========================

class OrderCreateForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = [
            "customer_name", "email", "phone",
            "vehicle_make", "vehicle_model", "vehicle_year",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4, "placeholder": "Additional information for the order..."})
        }
        labels = {
            "customer_name": "Full name",
            "email": "Email",
            "phone": "Phone",
            "vehicle_make": "Vehicle make",
            "vehicle_model": "Vehicle model",
            "vehicle_year": "Vehicle year",
            "notes": "Notes",
        }
