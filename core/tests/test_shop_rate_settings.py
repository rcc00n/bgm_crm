from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import AboutPageCopy, ClientPortalPageCopy, ShopRateLine, ShopRateSettings, UserProfile


class SharedShopRateRenderingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="shop-rate-user",
            email="shop-rate@example.com",
            password="StrongPass123!",
        )
        UserProfile.objects.create(user=self.user, phone="+14035550123")
        self.settings_obj = ShopRateSettings.get_solo()

    def _replace_rates(self, *rows):
        self.settings_obj.rate_rows.all().delete()
        for index, (label, display_rate) in enumerate(rows, start=1):
            ShopRateLine.objects.create(
                settings=self.settings_obj,
                label=label,
                display_rate=display_rate,
                sort_order=index * 10,
            )

    def test_our_story_uses_shared_rate_rows(self):
        self._replace_rates(
            ("Mechanical Service", "$140 / hr"),
            ("Design & Engineering", "$150 / hr"),
            ("Customer-Supplied Parts", "$145 / hr"),
        )

        about_copy = AboutPageCopy.get_solo()
        about_copy.rates_shop_value = "222/about-local"
        about_copy.rates_cad_value = "333/about-design-local"
        about_copy.rates_customer_parts_value = "444/about-parts-local"
        about_copy.save(
            update_fields=[
                "rates_shop_value",
                "rates_cad_value",
                "rates_customer_parts_value",
                "updated_at",
            ]
        )

        response = self.client.get(reverse("our-story"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mechanical Service")
        self.assertContains(response, "$140 / hr")
        self.assertContains(response, "Design &amp; Engineering")
        self.assertContains(response, "$150 / hr")
        self.assertContains(response, "Customer-Supplied Parts")
        self.assertContains(response, "$145 / hr")
        self.assertNotContains(response, "222/about-local")
        self.assertNotContains(response, "333/about-design-local")
        self.assertNotContains(response, "444/about-parts-local")

    def test_client_dashboard_uses_shared_rate_rows(self):
        self._replace_rates(
            ("Mechanical Service", "$140 / hr"),
            ("Custom Fabrication", "$145 / hr"),
            ("Specialty / European", "$150 / hr"),
        )

        portal_copy = ClientPortalPageCopy.get_solo()
        portal_copy.rates_shop_value = "111/portal-local"
        portal_copy.rates_cad_value = "222/portal-design-local"
        portal_copy.rates_customer_parts_value = "333/portal-parts-local"
        portal_copy.save(
            update_fields=[
                "rates_shop_value",
                "rates_cad_value",
                "rates_customer_parts_value",
                "updated_at",
            ]
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mechanical Service")
        self.assertContains(response, "Custom Fabrication")
        self.assertContains(response, "Specialty / European")
        self.assertContains(response, "$140 / hr")
        self.assertContains(response, "$145 / hr")
        self.assertContains(response, "$150 / hr")
        self.assertNotContains(response, "111/portal-local")
        self.assertNotContains(response, "222/portal-design-local")
        self.assertNotContains(response, "333/portal-parts-local")

    def test_shared_rate_rows_allow_add_and_remove(self):
        self._replace_rates(
            ("Mechanical Service", "$140 / hr"),
            ("Design & Engineering", "$150 / hr"),
        )

        self.assertEqual(
            ShopRateSettings.get_rate_rows(),
            [
                {"label": "Mechanical Service", "display_rate": "$140 / hr"},
                {"label": "Design & Engineering", "display_rate": "$150 / hr"},
            ],
        )

        self.settings_obj.rate_rows.filter(label="Mechanical Service").delete()
        ShopRateLine.objects.create(
            settings=self.settings_obj,
            label="New Specialty Rate",
            display_rate="$175 / hr",
            sort_order=30,
        )

        self.assertEqual(
            ShopRateSettings.get_rate_rows(),
            [
                {"label": "Design & Engineering", "display_rate": "$150 / hr"},
                {"label": "New Specialty Rate", "display_rate": "$175 / hr"},
            ],
        )
