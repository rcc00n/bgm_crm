from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from core.validators import clean_phone


class PhoneValidatorTests(SimpleTestCase):
    def test_accepts_e164_with_plus(self):
        self.assertEqual(clean_phone("+14035550100"), "+14035550100")

    def test_accepts_digits_only(self):
        self.assertEqual(clean_phone("14035550100"), "14035550100")

    def test_rejects_invalid_format(self):
        with self.assertRaises(ValidationError):
            clean_phone("123-456-7890")
