import re
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AdminFavoritePage
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

    def test_workspace_hub_exposes_anchor_highlight_hooks(self):
        response = self.client.get(reverse("admin-workspace-hub", kwargs={"slug": "scheduling-shop"}), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "workspace-hub-page", html=False)
        self.assertContains(response, "data-workspace-jumpbar", html=False)
        self.assertContains(response, "data-workspace-jump-link", html=False)
        self.assertContains(response, "data-workspace-jump-target=\"workspace-card-1\"", html=False)
        self.assertContains(response, "data-workspace-section", html=False)
        self.assertContains(response, "IntersectionObserver", html=False)
        self.assertContains(response, "workspace-jumpbar__link.is-active", html=False)

    def test_non_workspace_pages_include_sticky_topbar_rule(self):
        response = self.client.get(reverse("admin-whats-new"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "body:not(.workspace-hub-page) .main-header", html=False)
        self.assertContains(response, "position: sticky;", html=False)
        self.assertNotContains(response, "data-workspace-jumpbar", html=False)

    def test_whats_new_is_paginated_to_fifteen_entries_per_page(self):
        base_time = timezone.now()
        releases = [
            {
                "key": f"release-{index}",
                "published_at": base_time - timedelta(minutes=index),
                "title": f"Release {index}",
                "summary": f"Summary {index}",
                "highlights": [],
                "areas": [],
                "links": [],
            }
            for index in range(17, 0, -1)
        ]

        with patch("core.views.get_admin_releases", return_value=releases):
            page_one = self.client.get(reverse("admin-whats-new"), secure=True)
            page_two = self.client.get(reverse("admin-whats-new"), {"page": 2}, secure=True)

        self.assertEqual(page_one.status_code, 200)
        self.assertContains(page_one, "15 per page")
        self.assertContains(page_one, "Page 1 of 2")
        self.assertContains(page_one, "Release 17")
        self.assertContains(page_one, "Release 3")
        self.assertNotContains(page_one, "Release 2")
        self.assertContains(page_one, "?page=2", html=False)

        self.assertEqual(page_two.status_code, 200)
        self.assertContains(page_two, "Page 2 of 2")
        self.assertContains(page_two, "Release 2")
        self.assertContains(page_two, "Release 1")
        self.assertNotContains(page_two, "Release 17")
        self.assertContains(page_two, "?page=1", html=False)

    def test_sidebar_does_not_render_brand_or_sidebar_user_panel(self):
        response = self.client.get(reverse("admin:index"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="jazzy-logo"', html=False)
        self.assertNotContains(response, 'class="user-panel mt-3 pb-3 mb-3 d-flex"', html=False)

    def test_favorites_badge_uses_green_modifier(self):
        AdminFavoritePage.objects.create(
            user=self.superuser,
            url=reverse("admin:index"),
            label="Dashboard",
            icon="fas fa-th-large",
            category="Admin",
            note="Pinned dashboard.",
        )

        response = self.client.get(reverse("admin:index"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admin-notify-badge admin-notify-badge--success", html=False)
        self.assertContains(response, ".admin-notify-badge--success", html=False)
        self.assertContains(response, "background: #22c55e;", html=False)

    def test_sidebar_includes_reliable_fixed_scroll_hooks(self):
        response = self.client.get(reverse("admin:index"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "layout-fixed")
        self.assertContains(response, ".main-sidebar {", html=False)
        self.assertContains(response, "position: fixed;", html=False)
        self.assertContains(response, "display: flex;", html=False)
        self.assertContains(response, "height: var(--admin-sidebar-vh, 100vh);", html=False)
        self.assertContains(response, "max-height: var(--admin-sidebar-vh, 100vh);", html=False)
        self.assertContains(response, "min-height: 0;", html=False)
        self.assertContains(response, "overflow-y: auto;", html=False)
        self.assertContains(response, "scrollbar-gutter: stable;", html=False)
        self.assertContains(response, "--admin-sidebar-vh", html=False)

    def test_sidebar_items_follow_requested_workflow_order(self):
        response = self.client.get(reverse("admin:index"), secure=True)

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        start = body.index('<aside class="main-sidebar')
        end = body.index("</aside>", start)
        sidebar = body[start:end]
        pattern = re.compile(
            r'<li class="nav-item">\s*<a href="([^"]+)" class="nav-link[^"]*">\s*<i class="nav-icon [^"]+"></i>\s*<p>\s*([^<]+?)\s*(?:<|$)',
            re.S,
        )

        labels = [label for _, label in pattern.findall(sidebar)]
        expected_labels = [
            "Dashboard",
            "Calendar",
            "Scheduling &amp; Shop",
            "Catalog, Merch &amp; Fulfillment",
            "Insights &amp; QA",
            "Clients &amp; Leads",
            "Content, Brand &amp; Assets",
            "Email &amp; Campaigns",
            "Onboarding",
        ]
        self.assertEqual(labels[: len(expected_labels)], expected_labels)

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
            "automation": "email-campaigns",
            "brand-assets": "page-content",
            "orders-fulfillment": "catalog-merch",
            "booking-payments": "scheduling-shop",
            "payments-promotions": "scheduling-shop",
            "crm-vehicles": "scheduling-shop",
            "people-access": "scheduling-shop",
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

    def test_email_workspace_renders_telegramm_bot_at_bottom(self):
        response = self.client.get(reverse("admin-workspace-hub", kwargs={"slug": "email-campaigns"}), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email &amp; campaigns workspace")
        self.assertContains(response, "Email monitoring and publishing")
        self.assertContains(response, "Telegramm Bot")
        body = response.content.decode()
        self.assertLess(body.index("Email monitoring and publishing</h2>"), body.index("Telegramm Bot</h2>"))

    def test_combined_store_and_moved_reference_workspaces_render_expected_sections(self):
        store_response = self.client.get(reverse("admin-workspace-hub", kwargs={"slug": "catalog-merch"}), secure=True)
        scheduling_response = self.client.get(reverse("admin-workspace-hub", kwargs={"slug": "scheduling-shop"}), secure=True)

        self.assertEqual(store_response.status_code, 200)
        self.assertContains(store_response, "Catalog, merch &amp; fulfillment workspace")
        self.assertContains(store_response, "Catalog cockpit")
        self.assertContains(store_response, "Orders and fulfillment")
        self.assertContains(store_response, "Store rules and merch economics")

        self.assertEqual(scheduling_response.status_code, 200)
        self.assertContains(scheduling_response, "Payments and promotions")
        self.assertContains(scheduling_response, "Booking and payment references")
        self.assertContains(scheduling_response, "CRM, vehicles, and access")

    def test_whats_new_entries_include_links_to_updated_sections(self):
        response = self.client.get(reverse("admin-whats-new"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "What&#x27;s New now shows 15 updates per page")
        self.assertContains(response, "Topbar now stays visible on admin pages without section jump links")
        self.assertContains(response, "Sidebar stays pinned and follows the new work order")
        self.assertContains(response, "Sidebar now stays visible while you scroll")
        self.assertContains(response, "Favorites badge is now green in the header")
        self.assertContains(response, "Sidebar header and sidebar user panel removed")
        self.assertContains(response, "Telegramm Bot moved into the Email &amp; Campaigns hub")
        self.assertContains(
            response,
            reverse("admin-workspace-hub", kwargs={"slug": "email-campaigns"}),
            html=False,
        )
        self.assertContains(response, "Workspace section numbers now react while you scroll")
        self.assertContains(response, "Scheduling &amp; Shop now includes payments, promotions, CRM, and vehicles")
        self.assertContains(
            response,
            reverse("admin-workspace-hub", kwargs={"slug": "scheduling-shop"}),
            html=False,
        )
        self.assertContains(response, "What&#x27;s New entries now link straight to updated sections")
        self.assertContains(response, reverse("admin-whats-new"), html=False)
        self.assertContains(
            response,
            reverse("admin-workspace-hub", kwargs={"slug": "catalog-merch"}),
            html=False,
        )
        self.assertContains(
            response,
            reverse("admin-workspace-hub", kwargs={"slug": "page-content"}),
            html=False,
        )
        self.assertContains(response, reverse("admin:store_product_changelist"), html=False)
        self.assertContains(response, "/admin/whats-new/?page=2", html=False)
        self.assertContains(response, "Catalog, Merch &amp; Fulfillment")
