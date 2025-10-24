# core/validators.py
import re
from django.core.exceptions import ValidationError

PHONE_RE = re.compile(r"^\+?\d{10,15}$")      # leading "+" optional, expect 10-15 digits

def clean_phone(value):
    """Ensure the phone number follows the international format."""
    if not PHONE_RE.fullmatch(value):
        raise ValidationError("Enter a phone number in the format +12345678901.")
    return value
