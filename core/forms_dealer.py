from __future__ import annotations

from datetime import date

import phonenumbers
from phonenumbers.phonenumberutil import NumberParseException

from django import forms

from core.models import DealerTier, DealerTierLevel
from core.utils import format_currency


def _normalize_phone(raw: str) -> str:
    raw = (raw or "").strip()
    raw = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
    if raw and not raw.startswith("+"):
        raw = "+1" + raw
    try:
        parsed = phonenumbers.parse(raw, None)
    except NumberParseException:
        raise forms.ValidationError("Invalid phone format.")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def _tier_choices() -> list[tuple[str, str]]:
    try:
        tiers = list(
            DealerTierLevel.objects.filter(is_active=True).order_by(
                "minimum_spend", "sort_order", "code"
            )
        )
    except Exception:
        tiers = []

    if tiers:
        return [
            (
                tier.code,
                f"{tier.label} — {format_currency(tier.minimum_spend)}+ · {tier.discount_percent}% off",
            )
            for tier in tiers
        ]

    return list(DealerTier.choices)


class DealerApplyBusinessForm(forms.Form):
    business_name = forms.CharField(label="Business Name", max_length=128)
    operating_as = forms.CharField(
        label="Operating As (if different)", max_length=128, required=False
    )
    phone = forms.CharField(label="Phone", max_length=32)
    email = forms.EmailField(label="Email")
    website = forms.URLField(label="Website", required=False)
    years_in_business = forms.IntegerField(
        label="Years in Business", min_value=0, required=False
    )
    business_type = forms.CharField(label="Type of Business", max_length=120)
    preferred_tier = forms.ChoiceField(
        label="Projected tier",
        required=False,
        choices=[],
        help_text="Optional: select the tier that matches your planned annual CAD volume.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["preferred_tier"].choices = _tier_choices()

    def clean_phone(self):
        return _normalize_phone(self.cleaned_data.get("phone"))


class DealerApplyAddressForm(forms.Form):
    business_address = forms.CharField(
        label="Business Address",
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    city = forms.CharField(label="City", max_length=80)
    province = forms.CharField(label="Province / State", max_length=80)
    postal_code = forms.CharField(label="Postal / ZIP Code", max_length=20)
    gst_tax_id = forms.CharField(label="GST / Tax ID", max_length=64, required=False)
    business_license_number = forms.CharField(
        label="Business License #", max_length=64, required=False
    )
    resale_certificate_number = forms.CharField(
        label="Resale Certificate #", max_length=64, required=False
    )


class DealerApplyReferencesForm(forms.Form):
    reference_1_name = forms.CharField(label="Reference 1 (Name)", max_length=120)
    reference_1_phone = forms.CharField(label="Reference 1 (Phone)", max_length=32)
    reference_1_email = forms.EmailField(label="Reference 1 (Email)")

    reference_2_name = forms.CharField(label="Reference 2 (Name)", max_length=120)
    reference_2_phone = forms.CharField(label="Reference 2 (Phone)", max_length=32)
    reference_2_email = forms.EmailField(label="Reference 2 (Email)")

    def clean_reference_1_phone(self):
        return _normalize_phone(self.cleaned_data.get("reference_1_phone"))

    def clean_reference_2_phone(self):
        return _normalize_phone(self.cleaned_data.get("reference_2_phone"))


class DealerApplySignatureForm(forms.Form):
    authorized_signature_printed_name = forms.CharField(
        label="Authorized Signature: Printed Name", max_length=160
    )
    authorized_signature_title = forms.CharField(label="Title", max_length=120)
    authorized_signature_date = forms.DateField(
        label="Date",
        initial=date.today,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

