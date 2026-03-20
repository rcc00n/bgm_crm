from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from store.models import Category, Product


class AdminWorkspaceUiTests(TestCase):
    def setUp(self):
        self.superuser = get_user_model().objects.create_superuser(
            username="workspace-admin",
            email="workspace-admin@example.com",
            password="StrongPass123!",
        )
        self.client.force_login(self.superuser)

    def test_workspace_hub_includes_rule_to_hide_empty_header_strip(self):
        response = self.client.get(reverse("admin-workspace-hub", kwargs={"slug": "scheduling-shop"}), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Scheduling &amp; Shop")
        self.assertContains(
            response,
            ".content.border-bottom.mb-2:not(:has(h1:not(:empty))):not(:has(.breadcrumb)):not(:has(.breadcrumbs))",
        )

    def test_product_changelist_still_renders_heading_and_breadcrumbs(self):
        category = Category.objects.create(name="Admin Products", slug="admin-products")
        Product.objects.create(
            name="Admin Test Product",
            slug="admin-test-product",
            sku="BGM-ADMIN-TEST-1",
            category=category,
            price=Decimal("99.00"),
            inventory=3,
            is_active=True,
        )

        response = self.client.get(reverse("admin:store_product_changelist"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inventory watch")
        self.assertContains(response, "<ol class=\"breadcrumb\">", html=False)
        self.assertContains(response, "/admin/store/", html=False)
        self.assertContains(response, "Products")

    def test_legacy_workspace_slugs_redirect_to_combined_hubs(self):
        redirects = {
            "brand-assets": "page-content",
            "orders-fulfillment": "catalog-merch",
            "booking-payments": "scheduling-shop",
            "people-access": "crm-vehicles",
        }

        for old_slug, new_slug in redirects.items():
            with self.subTest(old_slug=old_slug):
                response = self.client.get(
                    reverse("admin-workspace-hub", kwargs={"slug": old_slug}),
                    secure=True,
                )
                self.assertRedirects(
                    response,
                    reverse("admin-workspace-hub", kwargs={"slug": new_slug}),
                    status_code=302,
                    fetch_redirect_response=False,
                )

    def test_combined_content_workspace_renders_custom_sections(self):
        response = self.client.get(reverse("admin-workspace-hub", kwargs={"slug": "page-content"}), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Content, brand &amp; assets workspace")
        self.assertContains(response, "Page editors")
        self.assertContains(response, "Brand system and chrome")
        self.assertContains(response, "Media and backgrounds")
        self.assertContains(response, "More Editors")

    def test_combined_store_and_moved_reference_workspaces_render_expected_sections(self):
        store_response = self.client.get(reverse("admin-workspace-hub", kwargs={"slug": "catalog-merch"}), secure=True)
        scheduling_response = self.client.get(reverse("admin-workspace-hub", kwargs={"slug": "scheduling-shop"}), secure=True)
        crm_response = self.client.get(reverse("admin-workspace-hub", kwargs={"slug": "crm-vehicles"}), secure=True)

        self.assertEqual(store_response.status_code, 200)
        self.assertContains(store_response, "Catalog, merch &amp; fulfillment workspace")
        self.assertContains(store_response, "Catalog cockpit")
        self.assertContains(store_response, "Orders and fulfillment")
        self.assertContains(store_response, "Store rules and merch economics")

        self.assertEqual(scheduling_response.status_code, 200)
        self.assertContains(scheduling_response, "Booking and payment references")

        self.assertEqual(crm_response.status_code, 200)
        self.assertContains(crm_response, "People and access")

    def test_whats_new_entries_include_links_to_updated_sections(self):
        response = self.client.get(reverse("admin-whats-new"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "What&#x27;s New entries now link straight to updated sections")
        self.assertContains(response, reverse("admin-whats-new"), html=False)
        self.assertContains(
            response,
            reverse("admin-workspace-hub", kwargs={"slug": "catalog-merch"}),
            html=False,
        )
        self.assertContains(response, "Catalog, Merch &amp; Fulfillment")
