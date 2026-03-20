from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import AdminLoginBranding
from store.models import Category, StorePricingSettings


class AdminSingletonRedirectTests(TestCase):
    def setUp(self):
        self.superuser = get_user_model().objects.create_superuser(
            username="singleton-admin",
            email="singleton-admin@example.com",
            password="StrongPass123!",
        )
        self.client.force_login(self.superuser)

    def test_singleton_model_changelist_redirects_to_change_form(self):
        branding = AdminLoginBranding.objects.create(login_logo_alt="Admin")

        response = self.client.get(reverse("admin:core_adminloginbranding_changelist"), secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"],
            reverse("admin:core_adminloginbranding_change", args=[branding.pk]),
        )

    def test_singleton_like_model_changelist_redirects_to_change_form(self):
        settings_obj = StorePricingSettings.objects.create(price_multiplier_percent=110)

        response = self.client.get(reverse("admin:store_storepricingsettings_changelist"), secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"],
            reverse("admin:store_storepricingsettings_change", args=[settings_obj.pk]),
        )

    def test_singleton_changelist_querystring_keeps_list_view_accessible(self):
        StorePricingSettings.objects.create(price_multiplier_percent=105)

        response = self.client.get(
            reverse("admin:store_storepricingsettings_changelist"),
            {"changelist": "1"},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)

    def test_regular_model_with_single_row_still_uses_changelist(self):
        Category.objects.create(name="Only category", slug="only-category")

        response = self.client.get(reverse("admin:store_category_changelist"), secure=True)

        self.assertEqual(response.status_code, 200)
