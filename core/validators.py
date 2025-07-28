# core/validators.py
import re
from django.core.exceptions import ValidationError

PHONE_RE = re.compile(r"^\+?\d{10,15}$")      # «+» необязателен, 10-15 цифр

def clean_phone(value):
    """Проверяет, что телефон соответствует международному формату."""
    if not PHONE_RE.fullmatch(value):
        raise ValidationError("Введите телефон в формате +79991234567")
    return value
