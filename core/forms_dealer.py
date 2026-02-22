from __future__ import annotations

from datetime import date

import phonenumbers
from phonenumbers.phonenumberutil import NumberParseException

from django import forms



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



CANADA_PROVINCE_STATE_CHOICES: list[tuple[str, str]] = [
    ("Alberta", "Alberta"),
    ("British Columbia", "British Columbia"),
    ("Manitoba", "Manitoba"),
    ("New Brunswick", "New Brunswick"),
    ("Newfoundland and Labrador", "Newfoundland and Labrador"),
    ("Nova Scotia", "Nova Scotia"),
    ("Northwest Territories", "Northwest Territories"),
    ("Nunavut", "Nunavut"),
    ("Ontario", "Ontario"),
    ("Prince Edward Island", "Prince Edward Island"),
    ("Quebec", "Quebec"),
    ("Saskatchewan", "Saskatchewan"),
    ("Yukon", "Yukon"),
]

USA_PROVINCE_STATE_CHOICES: list[tuple[str, str]] = [
    ("Alabama", "Alabama"),
    ("Alaska", "Alaska"),
    ("Arizona", "Arizona"),
    ("Arkansas", "Arkansas"),
    ("California", "California"),
    ("Colorado", "Colorado"),
    ("Connecticut", "Connecticut"),
    ("Delaware", "Delaware"),
    ("District of Columbia", "District of Columbia"),
    ("Florida", "Florida"),
    ("Georgia", "Georgia"),
    ("Hawaii", "Hawaii"),
    ("Idaho", "Idaho"),
    ("Illinois", "Illinois"),
    ("Indiana", "Indiana"),
    ("Iowa", "Iowa"),
    ("Kansas", "Kansas"),
    ("Kentucky", "Kentucky"),
    ("Louisiana", "Louisiana"),
    ("Maine", "Maine"),
    ("Maryland", "Maryland"),
    ("Massachusetts", "Massachusetts"),
    ("Michigan", "Michigan"),
    ("Minnesota", "Minnesota"),
    ("Mississippi", "Mississippi"),
    ("Missouri", "Missouri"),
    ("Montana", "Montana"),
    ("Nebraska", "Nebraska"),
    ("Nevada", "Nevada"),
    ("New Hampshire", "New Hampshire"),
    ("New Jersey", "New Jersey"),
    ("New Mexico", "New Mexico"),
    ("New York", "New York"),
    ("North Carolina", "North Carolina"),
    ("North Dakota", "North Dakota"),
    ("Ohio", "Ohio"),
    ("Oklahoma", "Oklahoma"),
    ("Oregon", "Oregon"),
    ("Pennsylvania", "Pennsylvania"),
    ("Rhode Island", "Rhode Island"),
    ("South Carolina", "South Carolina"),
    ("South Dakota", "South Dakota"),
    ("Tennessee", "Tennessee"),
    ("Texas", "Texas"),
    ("Utah", "Utah"),
    ("Vermont", "Vermont"),
    ("Virginia", "Virginia"),
    ("Washington", "Washington"),
    ("West Virginia", "West Virginia"),
    ("Wisconsin", "Wisconsin"),
    ("Wyoming", "Wyoming"),
]

PROVINCE_STATE_CHOICES: list[tuple[str, object]] = [
    ("", "Select province/state"),
    ("Canada", CANADA_PROVINCE_STATE_CHOICES),
    ("USA", USA_PROVINCE_STATE_CHOICES),
]


def _flatten_choices(choices: list[tuple[str, object]]) -> set[str]:
    values: set[str] = set()
    for value, label in choices:
        if isinstance(label, (list, tuple)):
            for sub_value, _sub_label in label:
                values.add(str(sub_value))
            continue
        values.add(str(value))
    return values


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
    def clean_phone(self):
        return _normalize_phone(self.cleaned_data.get("phone"))


class DealerApplyAddressForm(forms.Form):
    business_address = forms.CharField(
        label="Business Address",
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    city = forms.CharField(label="City", max_length=80)
    province = forms.ChoiceField(label="Province / State", choices=PROVINCE_STATE_CHOICES)
    postal_code = forms.CharField(label="Postal / ZIP Code", max_length=20)
    gst_tax_id = forms.CharField(label="GST / Tax ID", max_length=64, required=False)
    business_license_number = forms.CharField(
        label="Business License #", max_length=64, required=False
    )
    resale_certificate_number = forms.CharField(
        label="Resale Certificate #", max_length=64, required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Preserve legacy values that were previously typed free-form.
        existing = ""
        if self.is_bound:
            existing = str(self.data.get("province") or "").strip()
        else:
            existing = str(self.initial.get("province") or "").strip()
        if existing and existing not in _flatten_choices(list(self.fields["province"].choices or [])):
            self.fields["province"].choices = [
                ("", "Select province/state"),
                ("Current value", [(existing, existing)]),
                ("Canada", CANADA_PROVINCE_STATE_CHOICES),
                ("USA", USA_PROVINCE_STATE_CHOICES),
            ]


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
