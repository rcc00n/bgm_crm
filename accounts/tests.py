from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.forms import ClientProfileForm, ClientRegistrationForm
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
            "email_product_updates": True,
            "email_service_updates": False,
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
        self.assertTrue(user.userprofile.email_product_updates)
        self.assertFalse(user.userprofile.email_service_updates)
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


class ClientProfileFormTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="profile-user",
            email="profile@example.com",
            password="StrongPass123!",
        )
        UserProfile.objects.create(user=self.user, phone="+14035550101")

    def _base_data(self):
        return {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "profile+new@example.com",
            "phone": "403-555-0102",
            "birth_date": "1980-01-02",
            "address": "456 Main St",
            "how_heard": "facebook",
            "email_marketing_consent": True,
            "email_product_updates": True,
            "email_service_updates": True,
        }

    def test_valid_form_updates_user_and_profile(self):
        form = ClientProfileForm(data=self._base_data(), user=self.user)
        self.assertTrue(form.is_valid(), form.errors)

        user = form.save()
        user.refresh_from_db()
        profile = user.userprofile
        self.assertEqual(user.first_name, "Jane")
        self.assertEqual(user.last_name, "Doe")
        self.assertEqual(user.email, "profile+new@example.com")
        self.assertEqual(profile.phone, "+14035550102")
        self.assertEqual(profile.address, "456 Main St")
        self.assertTrue(profile.email_marketing_consent)
        self.assertTrue(profile.email_product_updates)
        self.assertTrue(profile.email_service_updates)
        self.assertIsNotNone(profile.email_marketing_consented_at)

    def test_rejects_duplicate_email(self):
        User = get_user_model()
        User.objects.create_user(
            username="other-user",
            email="duplicate@example.com",
            password="StrongPass123!",
        )

        data = self._base_data()
        data["email"] = "duplicate@example.com"
        form = ClientProfileForm(data=data, user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_rejects_duplicate_phone(self):
        User = get_user_model()
        other_user = User.objects.create_user(
            username="other-user",
            email="other@example.com",
            password="StrongPass123!",
        )
        UserProfile.objects.create(user=other_user, phone="+14035550102")

        form = ClientProfileForm(data=self._base_data(), user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("phone", form.errors)
