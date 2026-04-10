from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import AboutPageCopy, ClientPortalPageCopy, ShopRateSettings, UserProfile


class SharedShopRateRenderingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="shop-rate-user",
            email="shop-rate@example.com",
            password="StrongPass123!",
        )
        UserProfile.objects.create(user=self.user, phone="+14035550123")

    def test_our_story_uses_shared_shop_rate_setting(self):
        settings_obj = ShopRateSettings.objects.get(singleton_id=1)
        settings_obj.our_shop_rate = "175/shared"
        settings_obj.save(update_fields=["our_shop_rate", "updated_at"])

        about_copy = AboutPageCopy.get_solo()
        about_copy.rates_shop_value = "222/about-local"
        about_copy.save(update_fields=["rates_shop_value", "updated_at"])

        response = self.client.get(reverse("our-story"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "175/shared")
        self.assertNotContains(response, "222/about-local")

    def test_client_dashboard_uses_shared_shop_rate_setting(self):
        settings_obj = ShopRateSettings.objects.get(singleton_id=1)
        settings_obj.our_shop_rate = "185/shared"
        settings_obj.save(update_fields=["our_shop_rate", "updated_at"])

        portal_copy = ClientPortalPageCopy.get_solo()
        portal_copy.rates_shop_value = "111/portal-local"
        portal_copy.save(update_fields=["rates_shop_value", "updated_at"])

        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "185/shared")
        self.assertNotContains(response, "111/portal-local")
