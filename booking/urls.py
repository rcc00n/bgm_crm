# booking/urls.py
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from accounts.views import HomeView, MerchPlaceholderView
from core.autocomplete import ServiceAutocomplete
from core.views import service_search
from django.conf import settings
from django.conf.urls.static import static
from core.views import DealerApplyWizardView, DealerEntryView, DealerStatusView
from core import views as core_views
from store import views as store_views
urlpatterns = [
    path("robots.txt", core_views.robots_txt, name="robots-txt"),
    path("analytics/collect/", core_views.analytics_collect, name="analytics-collect"),
    path("site-notice/signup/", core_views.site_notice_signup, name="site-notice-signup"),
    path("admin/logout/", core_views.admin_logout, name="admin-logout"),
    path(
        "admin/api/clients/<int:user_id>/contact/",
        core_views.admin_client_contact,
        name="admin-client-contact",
    ),
    path(
        "admin/api/clients/search/",
        core_views.admin_client_search,
        name="admin-client-search",
    ),
    path(
        "admin/analytics/collect/",
        core_views.admin_analytics_collect,
        name="admin-analytics-collect",
    ),
    path(
        "admin/search/",
        admin.site.admin_view(core_views.admin_global_search),
        name="admin-global-search",
    ),
    path(
        "admin/search/suggest/",
        admin.site.admin_view(core_views.admin_global_search_suggest),
        name="admin-global-search-suggest",
    ),
    path(
        "admin/navigation/track/",
        admin.site.admin_view(core_views.admin_navigation_track),
        name="admin-navigation-track",
    ),
    path(
        "admin/favorites/toggle/",
        admin.site.admin_view(core_views.admin_favorite_toggle),
        name="admin-favorite-toggle",
    ),
    path("admin/ui-check/run/", core_views.admin_ui_check_run, name="admin-ui-check-run"),
    path(
        "admin/notifications/read-all/",
        admin.site.admin_view(core_views.admin_notifications_read_all),
        name="admin-notifications-read-all",
    ),
    path(
        "admin/whats-new/",
        admin.site.admin_view(core_views.admin_whats_new),
        name="admin-whats-new",
    ),
    path(
        "admin/whats-new/read-all/",
        admin.site.admin_view(core_views.admin_releases_read_all),
        name="admin-releases-read-all",
    ),
    path(
        "admin/pagecopy/save-field/",
        admin.site.admin_view(core_views.admin_pagecopy_save_field),
        name="admin-pagecopy-save-field",
    ),
    path(
        "admin/pagecopy/save-draft/",
        admin.site.admin_view(core_views.admin_pagecopy_save_draft),
        name="admin-pagecopy-save-draft",
    ),
    path(
        "admin/pagecopy/save-fonts/",
        admin.site.admin_view(core_views.admin_pagecopy_save_fonts),
        name="admin-pagecopy-save-fonts",
    ),
    path(
        "admin/pagecopy/save-font-styles/",
        admin.site.admin_view(core_views.admin_pagecopy_save_font_styles),
        name="admin-pagecopy-save-font-styles",
    ),
    path(
        "admin/pagecopy/save-section-layout/",
        admin.site.admin_view(core_views.admin_pagecopy_save_section_layout),
        name="admin-pagecopy-save-section-layout",
    ),
    path(
        "admin/pagecopy/save-section-order/",
        admin.site.admin_view(core_views.admin_pagecopy_save_section_order),
        name="admin-pagecopy-save-section-order",
    ),
    path(
        "admin/pagecopy/upload-font/",
        admin.site.admin_view(core_views.admin_pagecopy_upload_font),
        name="admin-pagecopy-upload-font",
    ),
    path(
        "admin/staffing/time-tracking/",
        admin.site.admin_view(core_views.admin_staff_usage),
        name="admin-staff-usage",
    ),
    path(
        "admin/staff-guide/",
        admin.site.admin_view(core_views.admin_staff_guide),
        name="admin-staff-guide",
    ),
    path(
        "admin/workspaces/operations/",
        admin.site.admin_view(core_views.admin_workspace_operations),
        name="admin-workspace-operations",
    ),
    path(
        "admin/workspaces/customers-sales/",
        admin.site.admin_view(core_views.admin_workspace_customers_sales),
        name="admin-workspace-customers-sales",
    ),
    path(
        "admin/workspaces/website-marketing/",
        admin.site.admin_view(core_views.admin_workspace_website_marketing),
        name="admin-workspace-website-marketing",
    ),
    path(
        "admin/workspaces/reporting-access/",
        admin.site.admin_view(core_views.admin_workspace_reporting_access),
        name="admin-workspace-reporting-access",
    ),
    path(
        "admin/workspaces/reference-setup/",
        admin.site.admin_view(core_views.admin_workspace_reference_setup),
        name="admin-workspace-reference-setup",
    ),
    path(
        "admin/workspaces/<slug:slug>/",
        admin.site.admin_view(core_views.admin_workspace_hub),
        name="admin-workspace-hub",
    ),
    path(
        "admin/analytics/insights/",
        admin.site.admin_view(core_views.admin_web_analytics_insights),
        name="admin-analytics-insights",
    ),
    path(
        "admin/storefront/merch/economics/",
        admin.site.admin_view(core_views.admin_merch_economics),
        name="admin-merch-economics",
    ),
    path(
        "admin/email/overview/",
        admin.site.admin_view(core_views.admin_email_overview),
        name="admin-email-overview",
    ),
    path(
        "admin/email/logs/",
        admin.site.admin_view(core_views.admin_email_logs),
        name="admin-email-logs",
    ),
    path(
        "admin/email/history/",
        admin.site.admin_view(core_views.admin_email_history),
        name="admin-email-history",
    ),
    path(
        "admin/email/campaigns/",
        admin.site.admin_view(core_views.admin_email_campaign_history),
        name="admin-email-campaign-history",
    ),
    path("ckeditor/", include("ckeditor_uploader.urls")),
    # Admin
    path("admin/", admin.site.urls),

    # Accounts
    path("accounts/", include("accounts.urls")),

    # Home
    path("", HomeView.as_view(), name="home"),
    path("review/", store_views.leave_review, name="leave-review"),

    # Autocomplete & API
    path("autocomplete/service/", ServiceAutocomplete.as_view(), name="service-autocomplete"),
    path("accounts/api/services/search/", service_search, name="service-search"),

    # === Store: основное подключение c namespace ===
    path("store/", include(("store.urls_store", "store"), namespace="store")),

    # === Алиасы для обратной совместимости (старые имена без namespace) ===
    # Главная магазина
    path("store/", RedirectView.as_view(pattern_name="store:store", permanent=False), name="store"),
    # Корзина
    path("store/cart/", RedirectView.as_view(pattern_name="store:store-cart", permanent=False), name="store-cart"),
    # Промокод в корзине
    path(
        "store/cart/promo/",
        RedirectView.as_view(pattern_name="store:store-cart-promo", permanent=False),
        name="store-cart-promo",
    ),
    # Checkout
    path("store/checkout/", RedirectView.as_view(pattern_name="store:store-checkout", permanent=False), name="store-checkout"),
    # Категория
    path(
        "store/category/<slug:slug>/",
        RedirectView.as_view(pattern_name="store:store-category", permanent=False),
        name="store-category",
    ),
    # Карточка товара
    path(
        "store/p/<slug:slug>/",
        RedirectView.as_view(pattern_name="store:store-product", permanent=False),
        name="store-product",
    ),
    # Корзина: добавить/удалить
    path(
        "store/cart/add/<slug:slug>/",
        RedirectView.as_view(pattern_name="store:store-cart-add", permanent=False),
        name="store-cart-add",
    ),
    path(
        "store/cart/remove/<slug:slug>/",
        RedirectView.as_view(pattern_name="store:store-cart-remove", permanent=False),
        name="store-cart-remove",
    ),

    # Merch (заглушка)
    path("merch/", MerchPlaceholderView.as_view(), name="merch"),
    
    path("dealer/", DealerEntryView.as_view(), name="dealer-entry"),
    path("dealer/apply/", DealerApplyWizardView.as_view(), name="dealer-apply"),
    path("dealer/apply/<slug:step>/", DealerApplyWizardView.as_view(), name="dealer-apply-step"),
    path("dealer/status/", DealerStatusView.as_view(), name="dealer-status"),
    path("financing/", core_views.financing_view, name="financing"),
    path("faq/", core_views.faq_view, name="faq"),
    path("our-story/", core_views.our_story_view, name="our-story"),
    path("qualify", core_views.qualify_view, name="qualify"),
    path("qualify/", RedirectView.as_view(pattern_name="qualify", permanent=False)),
    path("thank-you/", core_views.qualify_thank_you_view, name="qualify-thank-you"),
    path("services/", core_views.public_mainmenu, name="services"),
    # Hidden brake & suspension landing page (direct-link only)
    path("services/brake-suspension/", core_views.brake_suspension_view, name="services-brake-suspension"),
    # Hidden electrical work landing page (direct-link only)
    path("services/electrical-work/", core_views.electrical_work_view, name="services-electrical-work"),
    # Hidden wheel & tire landing page (direct-link only)
    path("services/wheel-tire/", core_views.wheel_tire_service_view, name="services-wheel-tire"),
    # Hidden general request intake (direct-link only)
    path("services/request/", core_views.general_service_request_view, name="services-general-request"),
    # Hidden performance tuning landing page (direct-link only)
    path("services/performance-tuning/", core_views.performance_tuning_view, name="services-performance-tuning"),
    path("services/lead/", core_views.submit_service_lead, name="service-lead-submit"),
    path("project-journal/", core_views.project_journal_view, name="project-journal"),
    path("project-journal/<slug:slug>/", core_views.project_journal_post_view, name="project-journal-post"),
    path("legal/terms/", core_views.TermsAndConditionsView.as_view(), name="legal-terms"),
    path("legal/<slug:slug>/", core_views.LegalPageView.as_view(), name="legal-page"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
