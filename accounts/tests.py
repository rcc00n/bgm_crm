from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.forms import ClientRegistrationForm
from core.models import UserProfile


class ClientRegistrationFormTests(TestCase):
    def _base_data(self):
        return {
            "username": "",
            "email": "tester@example.com",
            "phone": "403-555-0100",
            "address": "123 Main St",
            "how_heard": "google",
            "email_marketing_consent": True,
            "accepted_terms": True,
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
        }

    def test_valid_form_creates_user_profile_and_role(self):
        form = ClientRegistrationForm(data=self._base_data())
        self.assertTrue(form.is_valid(), form.errors)

        user = form.save()
        self.assertEqual(user.email, "tester@example.com")
        self.assertEqual(user.username, "tester")
        self.assertEqual(user.userprofile.phone, "+14035550100")
        self.assertEqual(user.userprofile.how_heard, "google")
        self.assertTrue(user.userprofile.email_marketing_consent)
        self.assertTrue(user.userrole_set.filter(role__name="Client").exists())

    def test_rejects_duplicate_email(self):
        User = get_user_model()
        User.objects.create_user(
            username="existing",
            email="tester@example.com",
            password="StrongPass123!",
        )

        form = ClientRegistrationForm(data=self._base_data())
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_rejects_duplicate_phone(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="existing",
            email="existing@example.com",
            password="StrongPass123!",
        )
        UserProfile.objects.create(user=user, phone="+14035550100")

        data = self._base_data()
        data["email"] = "new@example.com"
        form = ClientRegistrationForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("phone", form.errors)
