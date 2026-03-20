from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory
from django.test import TestCase
from django.urls import reverse

from accounts.views import ClientDashboardView, HomeView
from accounts.forms import ClientProfileForm, ClientRegistrationForm
from core.models import EmailSendLog, HomePageCopy, PageSection, UserProfile
from store.models import Category, MerchCategory, Product


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


class ClientDashboardNotificationEmailTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="dashboard-user",
            email="dashboard@example.com",
            password="StrongPass123!",
        )
        self.other = User.objects.create_user(
            username="other-dashboard-user",
            email="other-dashboard@example.com",
            password="StrongPass123!",
        )
        self.factory = RequestFactory()

    def _build_context(self, user):
        request = self.factory.get("/accounts/dashboard/")
        request.user = user
        view = ClientDashboardView()
        view.request = request
        return view.get_context_data()

    def test_notifications_include_only_successful_emails_for_current_user(self):
        EmailSendLog.objects.create(
            email_type="appointment_confirmation",
            subject="Your booking is confirmed",
            recipients=[self.user.email],
            recipient_count=1,
            success=True,
        )
        EmailSendLog.objects.create(
            email_type="order_confirmation",
            subject="Another user's order",
            recipients=[self.other.email],
            recipient_count=1,
            success=True,
        )
        EmailSendLog.objects.create(
            email_type="order_confirmation",
            subject="Failed send",
            recipients=[self.user.email],
            recipient_count=1,
            success=False,
        )

        context = self._build_context(self.user)
        notifications = context["notification_emails"]

        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["title"], "Your booking is confirmed")
        self.assertEqual(notifications[0]["tag"], "Appointment")

    def test_notifications_match_recipient_case_insensitively(self):
        EmailSendLog.objects.create(
            email_type="email_verification",
            subject="Verify your email",
            recipients=[self.user.email.upper()],
            recipient_count=1,
            success=True,
        )

        context = self._build_context(self.user)
        notifications = context["notification_emails"]

        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["title"], "Verify your email")
        self.assertEqual(notifications[0]["tag"], "Account")


class HomeViewProductCarouselTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.category = Category.objects.create(name="Tunes", slug="tunes")
        self.merch_category = MerchCategory.objects.create(name="Apparel", slug="apparel", is_active=True)

    def test_homepage_products_only_include_in_house_items(self):
        in_house = Product.objects.create(
            name="In-House Tune",
            slug="in-house-tune",
            sku="IH-1",
            category=self.category,
            price="100.00",
            is_active=True,
            is_in_house=True,
        )
        Product.objects.create(
            name="External Tune",
            slug="external-tune",
            sku="EXT-1",
            category=self.category,
            price="120.00",
            is_active=True,
            is_in_house=False,
        )
        Product.objects.create(
            name="In-House Merch",
            slug="merch-shirt",
            sku="PF-1",
            category=self.category,
            merch_category=self.merch_category,
            price="45.00",
            is_active=True,
            is_in_house=True,
        )

        request = self.factory.get("/")
        request.user = get_user_model()()
        view = HomeView()
        view.request = request

        context = view.get_context_data()

        self.assertEqual([product.id for product in context["home_products"]], [in_house.id])


class HomeViewPageSectionRenderingTests(TestCase):
    def setUp(self):
        self.home_url = reverse("home")
        self.home_copy = HomePageCopy.get_solo()
        self.home_copy.hero_title = "__default_home_title__"
        self.home_copy.hero_lead = "__default_home_lead__"
        self.home_copy.save(update_fields=["hero_title", "hero_lead"])
        self.content_type = ContentType.objects.get_for_model(HomePageCopy)
        PageSection.objects.filter(content_type=self.content_type, object_id=self.home_copy.pk).delete()

    def test_home_page_uses_standard_hero_when_no_page_sections_exist(self):
        response = self.client.get(self.home_url, secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "__default_home_title__")
        self.assertContains(response, "data-hero-carousel")
        self.assertNotContains(response, "builder-section--hero")

    def test_home_page_renders_page_builder_sections_when_present(self):
        PageSection.objects.create(
            content_type=self.content_type,
            object_id=self.home_copy.pk,
            section_type=PageSection.SectionType.HERO,
            order=10,
            config={
                "title": "__builder_home_title__",
                "body": "__builder_home_body__",
            },
        )

        response = self.client.get(self.home_url, secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "__builder_home_title__")
        self.assertContains(response, "__builder_home_body__")
        self.assertContains(response, "builder-section--hero")
        self.assertNotContains(response, "__default_home_title__")
        self.assertNotContains(response, "data-hero-carousel")
