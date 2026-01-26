from __future__ import annotations

from django import forms
from django.conf import settings
from typing import Any
import json
import re

from .models import (
    Product,
    Order,
    Category,
    CarMake,
    CarModel,
    CustomFitmentRequest,
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
        active_categories = Category.objects.filter(products__is_active=True).distinct()
        self.fields["category"].queryset = active_categories
        self.fields["category"].label_from_instance = lambda obj: obj.display_name
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
            "notes", "reference_image",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4, "placeholder": "Additional information for the order..."}),
            "reference_image": forms.ClearableFileInput(attrs={"accept": "image/*"}),
        }
        labels = {
            "customer_name": "Full name",
            "email": "Email",
            "phone": "Phone",
            "vehicle_make": "Vehicle make",
            "vehicle_model": "Vehicle model",
            "vehicle_year": "Vehicle year",
            "notes": "Notes",
            "reference_image": "Photo reference",
        }


# =========================
# Quote / custom fitment form
# =========================

class CustomFitmentRequestForm(forms.ModelForm):
    product = forms.ModelChoiceField(
        queryset=Product.objects.all(),
        required=False,
        widget=forms.HiddenInput,
    )
    source_url = forms.URLField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = CustomFitmentRequest
        fields = [
            "product",
            "customer_name",
            "email",
            "phone",
            "vehicle",
            "submodel",
            "performance_goals",
            "budget",
            "timeline",
            "message",
            "source_url",
        ]
        labels = {
            "vehicle": "Platform / chassis",
            "submodel": "Submodel / trim",
            "performance_goals": "Performance goals",
            "budget": "Budget",
            "timeline": "Timeline",
            "message": "Notes",
        }
        widgets = {
            "customer_name": forms.TextInput(
                attrs={"placeholder": "Full name", "class": "field", "autocomplete": "name"}
            ),
            "email": forms.EmailInput(
                attrs={"placeholder": "name@example.com", "class": "field", "autocomplete": "email"}
            ),
            "phone": forms.TextInput(
                attrs={"placeholder": "Phone (optional)", "class": "field", "autocomplete": "tel"}
            ),
            "vehicle": forms.TextInput(
                attrs={"placeholder": "E.g. 2020 F-350 crew cab", "class": "field"}
            ),
            "submodel": forms.TextInput(
                attrs={"placeholder": "Trim, submodel, or package", "class": "field"}
            ),
            "performance_goals": forms.TextInput(
                attrs={"placeholder": "Desired power / use case", "class": "field"}
            ),
            "budget": forms.TextInput(
                attrs={"placeholder": "Budget (optional)", "class": "field"}
            ),
            "timeline": forms.TextInput(
                attrs={"placeholder": "Target completion date", "class": "field"}
            ),
            "message": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Anything else we should know?",
                    "class": "field",
                }
            ),
        }

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        if not phone:
            return ""
        # keep digits, plus, and separators minimal to avoid user errors
        cleaned = "".join(ch for ch in phone if ch.isdigit() or ch in "+-() ")
        return cleaned.strip()


# =========================
# Admin: Product import
# =========================

class ProductImportForm(forms.Form):
    mode = forms.ChoiceField(
        label="Import format",
        choices=(
            ("auto", "Auto (Shopify or simple CSV/XLSX)"),
            ("shopify", "Shopify export"),
            ("simple", "Simple columns"),
        ),
        initial="auto",
        required=True,
    )
    file = forms.FileField(
        label="Price file",
        help_text="Upload a .csv or .xlsx file.",
    )
    default_category = forms.ModelChoiceField(
        label="Default category",
        queryset=Category.objects.all(),
        required=False,
        help_text="Used when a row has no category.",
    )
    default_currency = forms.CharField(
        label="Default currency",
        initial=getattr(settings, "DEFAULT_CURRENCY_CODE", "CAD"),
        required=False,
        help_text="Used when the file has no currency column.",
    )
    update_existing = forms.BooleanField(
        label="Update existing products (by SKU)",
        required=False,
        initial=False,
    )
    create_missing_categories = forms.BooleanField(
        label="Create missing categories",
        required=False,
        initial=True,
    )
    dieselr_foreign = forms.BooleanField(
        label="Diesel R / Foreing",
        required=False,
        initial=False,
        help_text="Multiply imported prices by 1.4.",
    )
    dry_run = forms.BooleanField(
        label="Dry run (no database changes)",
        required=False,
        initial=False,
    )
