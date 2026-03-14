from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.test.utils import override_settings
from django.utils import timezone
from django.utils.text import slugify

from core.models import (
    AboutPageCopy,
    AdminSidebarSeen,
    Appointment,
    AppointmentPrepayment,
    AppointmentPromoCode,
    AppointmentReview,
    AppointmentStatus,
    AppointmentStatusHistory,
    BackgroundAsset,
    BookingDayOverride,
    ClientFile,
    ClientSource,
    ClientUiCheckRun,
    DealerApplication,
    DealerTier,
    DealerTierLevel,
    EmailCampaign,
    EmailCampaignRecipient,
    EmailSendLog,
    EmailSubscriber,
    FAQPageCopy,
    HeroImage,
    HomePageCopy,
    LandingPageReview,
    LeadSubmissionEvent,
    LegalPage,
    MasterAvailability,
    MasterProfile,
    MasterRoom,
    MerchGalleryItem,
    MerchPageCopy,
    Notification,
    PageCopyDraft,
    PageSection,
    PageView,
    Payment,
    PaymentMethod,
    PaymentStatus,
    PrepaymentOption,
    ProjectJournalCategory,
    ProjectJournalEntry,
    ProjectJournalPhoto,
    PromoCode,
    Role,
    Service,
    ServiceCategory,
    ServiceDiscount,
    ServiceLead,
    ServiceMaster,
    ServicesPageCopy,
    SiteNoticeSignup,
    StaffLoginEvent,
    StorePageCopy,
    UserProfile,
    VisitorSession,
)
from core.utils import assign_role
from notifications.models import (
    TelegramBotSettings,
    TelegramContact,
    TelegramMessageLog,
    TelegramRecipientSlot,
    TelegramReminder,
)
from store.models import (
    AbandonedCart,
    CarMake,
    CarModel,
    Category,
    CleanupBatch,
    CustomFitmentRequest,
    ImportBatch,
    MerchCategory,
    Order,
    OrderItem,
    OrderPromoCode,
    PrintfulWebhookEvent,
    Product,
    ProductDiscount,
    ProductImage,
    ProductOption,
    StoreInventorySettings,
    StorePricingSettings,
    StoreReview,
    StoreShippingSettings,
)


DEMO_PASSWORD = "DemoPass123!"
DEMO_DOMAIN = "demo.local"
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+yf9sAAAAASUVORK5CYII="
)


@dataclass
class DemoUsers:
    admin: object
    coordinator: object
    masters: list
    clients: list
    dealers: list


class Command(BaseCommand):
    help = "Populate the local database with broad demo data for admin QA and UX walkthroughs."

    def handle(self, *args, **options):
        self.now = timezone.now()
        self.today = timezone.localdate()
        self.shared_password = DEMO_PASSWORD

        with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            with transaction.atomic():
                users = self._seed_users()
                refs = self._seed_reference_data(users)
                self._seed_content_and_marketing(users)
                self._seed_crm_and_leads(users)
                self._seed_appointments_and_payments(users, refs)
                self._seed_store(users, refs)
                self._seed_email_and_telegram(users)
                self._seed_analytics_and_logs(users)

        self.stdout.write(self.style.SUCCESS("Demo admin data seeded."))
        self.stdout.write(f"Shared demo password: {self.shared_password}")
        self.stdout.write(
            "Created/updated: "
            f"{get_user_model().objects.filter(username__startswith='demo_').count()} demo users, "
            f"{Appointment.objects.filter(contact_email__iendswith='@demo.local').count()} demo appointments, "
            f"{Order.objects.filter(email__iendswith='@demo.local').count()} demo orders, "
            f"{Product.objects.filter(sku__startswith='DEMO-').count()} demo products."
        )

    def _seed_users(self) -> DemoUsers:
        roles = {
            "Admin": Role.objects.get_or_create(name="Admin")[0],
            "Master": Role.objects.get_or_create(name="Master")[0],
            "Client": Role.objects.get_or_create(name="Client")[0],
            "Sales": Role.objects.get_or_create(name="Sales")[0],
        }

        admin = self._upsert_user(
            username="demo_admin",
            email=f"demo.admin@{DEMO_DOMAIN}",
            first_name="Demo",
            last_name="Admin",
            phone="+15550000001",
            roles=[roles["Admin"]],
            is_staff=True,
            is_superuser=True,
            marketing=True,
        )
        coordinator = self._upsert_user(
            username="demo_coordinator",
            email=f"demo.coordinator@{DEMO_DOMAIN}",
            first_name="Casey",
            last_name="Coordinator",
            phone="+15550000002",
            roles=[roles["Admin"], roles["Sales"]],
            is_staff=True,
            is_superuser=False,
            marketing=True,
        )

        masters = [
            self._upsert_user(
                username="demo_master_alex",
                email=f"alex.master@{DEMO_DOMAIN}",
                first_name="Alex",
                last_name="Mercer",
                phone="+15550000011",
                roles=[roles["Master"]],
                is_staff=True,
                marketing=False,
            ),
            self._upsert_user(
                username="demo_master_bri",
                email=f"bri.master@{DEMO_DOMAIN}",
                first_name="Bri",
                last_name="Tate",
                phone="+15550000012",
                roles=[roles["Master"]],
                is_staff=True,
                marketing=False,
            ),
            self._upsert_user(
                username="demo_master_cam",
                email=f"cam.master@{DEMO_DOMAIN}",
                first_name="Cam",
                last_name="Rivera",
                phone="+15550000013",
                roles=[roles["Master"]],
                is_staff=True,
                marketing=False,
            ),
        ]

        clients = []
        client_specs = [
            ("demo_client_jordan", "Jordan", "Vale", "+15550000101", True),
            ("demo_client_morgan", "Morgan", "Lee", "+15550000102", True),
            ("demo_client_ryan", "Ryan", "Stone", "+15550000103", False),
            ("demo_client_avery", "Avery", "Cole", "+15550000104", True),
            ("demo_client_sky", "Sky", "Nolan", "+15550000105", False),
            ("demo_client_taylor", "Taylor", "Reed", "+15550000106", True),
            ("demo_client_dakota", "Dakota", "Cross", "+15550000107", True),
            ("demo_client_blair", "Blair", "Quinn", "+15550000108", False),
        ]
        for username, first_name, last_name, phone, marketing in client_specs:
            clients.append(
                self._upsert_user(
                    username=username,
                    email=f"{username}@{DEMO_DOMAIN}",
                    first_name=first_name,
                    last_name=last_name,
                    phone=phone,
                    roles=[roles["Client"]],
                    marketing=marketing,
                )
            )

        dealers = [
            self._upsert_user(
                username="demo_dealer_approved",
                email=f"dealer.approved@{DEMO_DOMAIN}",
                first_name="Parker",
                last_name="Works",
                phone="+15550000201",
                roles=[roles["Client"]],
                marketing=True,
                is_dealer=True,
                dealer_tier=DealerTier.TIER_10,
            ),
            self._upsert_user(
                username="demo_dealer_pending",
                email=f"dealer.pending@{DEMO_DOMAIN}",
                first_name="Lane",
                last_name="Offroad",
                phone="+15550000202",
                roles=[roles["Client"]],
                marketing=True,
            ),
            self._upsert_user(
                username="demo_dealer_rejected",
                email=f"dealer.rejected@{DEMO_DOMAIN}",
                first_name="Quinn",
                last_name="Garage",
                phone="+15550000203",
                roles=[roles["Client"]],
                marketing=False,
            ),
        ]

        room_names = ["Bay A", "Bay B", "Dyno"]
        rooms = [MasterRoom.objects.get_or_create(room=name)[0] for name in room_names]
        profile_specs = [
            (masters[0], "Performance technician", "Tuning, drivability and diagnostics.", rooms[0], time(8, 0), time(17, 0)),
            (masters[1], "Electrical specialist", "Lighting, wiring and accessories.", rooms[1], time(9, 0), time(18, 0)),
            (masters[2], "Suspension fabricator", "Lift kits, alignment and wheel fitment.", rooms[2], time(10, 0), time(19, 0)),
        ]
        for user, profession, bio, room, work_start, work_end in profile_specs:
            profile, _ = MasterProfile.objects.update_or_create(
                user=user,
                defaults={
                    "profession": profession,
                    "bio": bio,
                    "room": room,
                    "work_start": work_start,
                    "work_end": work_end,
                },
            )
            if not profile.photo:
                profile.photo.save(f"{user.username}.png", self._image_file(), save=True)

        return DemoUsers(
            admin=admin,
            coordinator=coordinator,
            masters=masters,
            clients=clients,
            dealers=dealers,
        )

    def _seed_reference_data(self, users: DemoUsers) -> dict:
        service_categories = {
            "Performance": ServiceCategory.objects.get_or_create(name="Demo Performance")[0],
            "Electrical": ServiceCategory.objects.get_or_create(name="Demo Electrical")[0],
            "Suspension": ServiceCategory.objects.get_or_create(name="Demo Suspension")[0],
        }
        prepayments = {
            25: PrepaymentOption.objects.get_or_create(percent=25)[0],
            50: PrepaymentOption.objects.get_or_create(percent=50)[0],
            100: PrepaymentOption.objects.get_or_create(percent=100)[0],
        }
        payment_statuses = {
            "Unpaid": PaymentStatus.objects.get_or_create(name="Unpaid")[0],
            "Pending": PaymentStatus.objects.get_or_create(name="Pending")[0],
            "Paid": PaymentStatus.objects.get_or_create(name="Paid")[0],
            "Refunded": PaymentStatus.objects.get_or_create(name="Refunded")[0],
        }
        payment_methods = {
            "Card": PaymentMethod.objects.get_or_create(name="Card")[0],
            "Cash": PaymentMethod.objects.get_or_create(name="Cash")[0],
            "E-Transfer": PaymentMethod.objects.get_or_create(name="E-Transfer")[0],
            "Stripe": PaymentMethod.objects.get_or_create(name="Stripe")[0],
        }
        appointment_statuses = {
            "Scheduled": AppointmentStatus.objects.get_or_create(name="Scheduled")[0],
            "Confirmed": AppointmentStatus.objects.get_or_create(name="Confirmed")[0],
            "In Progress": AppointmentStatus.objects.get_or_create(name="In Progress")[0],
            "Completed": AppointmentStatus.objects.get_or_create(name="Completed")[0],
            "Cancelled": AppointmentStatus.objects.get_or_create(name="Cancelled")[0],
            "No Show": AppointmentStatus.objects.get_or_create(name="No Show")[0],
        }
        client_sources = [
            ClientSource.objects.get_or_create(source=value)[0]
            for value in ["Google", "Instagram", "Referral", "Dealer network"]
        ]

        services = {
            "dyno": self._upsert_service(
                "Demo Dyno Tune",
                category=service_categories["Performance"],
                base_price=Decimal("650.00"),
                duration=120,
                prepayment=prepayments[50],
                description="ECU tune with logs, revision notes and before/after review.",
            ),
            "lighting": self._upsert_service(
                "Demo Lighting Retrofit",
                category=service_categories["Electrical"],
                base_price=Decimal("420.00"),
                duration=90,
                prepayment=prepayments[25],
                description="Headlight retrofit with aiming and wiring cleanup.",
            ),
            "lift": self._upsert_service(
                "Demo Lift Kit Install",
                category=service_categories["Suspension"],
                base_price=Decimal("980.00"),
                duration=180,
                description="Full install, torque check and post-install inspection.",
            ),
            "diag": self._upsert_service(
                "Demo Wiring Diagnostics",
                category=service_categories["Electrical"],
                base_price=Decimal("180.00"),
                duration=60,
                description="Structured fault isolation and repair plan.",
            ),
            "alignment": self._upsert_service(
                "Demo Alignment Setup",
                category=service_categories["Suspension"],
                base_price=Decimal("210.00"),
                duration=75,
                description="Street or off-road alignment with printout.",
            ),
            "estimate": self._upsert_service(
                "Demo Custom Fabrication",
                category=service_categories["Performance"],
                base_price=Decimal("0.00"),
                duration=90,
                description="Estimate-only fabrication intake.",
                contact_for_estimate=True,
                estimate_from_price=Decimal("300.00"),
            ),
        }

        ServiceDiscount.objects.update_or_create(
            service=services["lighting"],
            discount_percent=10,
            defaults={
                "start_date": self.today - timedelta(days=3),
                "end_date": self.today + timedelta(days=20),
            },
        )
        ServiceDiscount.objects.update_or_create(
            service=services["alignment"],
            discount_percent=15,
            defaults={
                "start_date": self.today - timedelta(days=1),
                "end_date": self.today + timedelta(days=10),
            },
        )

        for master in users.masters:
            for service in services.values():
                ServiceMaster.objects.get_or_create(master=master, service=service)

        service_code = PromoCode.objects.get_or_create(
            code="DEMO-SERVICE-15",
            defaults={
                "discount_percent": 15,
                "active": True,
                "start_date": self.today - timedelta(days=5),
                "end_date": self.today + timedelta(days=25),
                "applies_to_services": True,
                "applies_to_products": False,
            },
        )[0]
        service_code.applicable_services.set([services["dyno"], services["lift"]])

        expired_code = PromoCode.objects.get_or_create(
            code="DEMO-EXPIRED-10",
            defaults={
                "discount_percent": 10,
                "active": True,
                "start_date": self.today - timedelta(days=40),
                "end_date": self.today - timedelta(days=5),
                "applies_to_services": True,
                "applies_to_products": True,
            },
        )[0]
        if expired_code.applicable_services.count() == 0:
            expired_code.applicable_services.set([services["diag"]])

        return {
            "service_categories": service_categories,
            "prepayments": prepayments,
            "payment_statuses": payment_statuses,
            "payment_methods": payment_methods,
            "appointment_statuses": appointment_statuses,
            "client_sources": client_sources,
            "services": services,
            "service_code": service_code,
            "expired_code": expired_code,
        }

    def _seed_content_and_marketing(self, users: DemoUsers) -> None:
        home_copy = self._get_solo(HomePageCopy)
        services_copy = self._get_solo(ServicesPageCopy)
        store_copy = self._get_solo(StorePageCopy)
        faq_copy = self._get_solo(FAQPageCopy)
        about_copy = self._get_solo(AboutPageCopy)
        merch_copy = self._get_solo(MerchPageCopy)

        self._clear_demo_page_overrides(home_copy)
        self._clear_demo_page_overrides(services_copy)
        self._clear_demo_page_overrides(store_copy)

        for title, category, order in [
            ("Demo Crew Tee", "Apparel", 10),
            ("Demo Patch Hat", "Headwear", 20),
            ("Demo Shop Banner", "Accessories", 30),
        ]:
            item, _ = MerchGalleryItem.objects.update_or_create(
                merch_page=merch_copy,
                title=title,
                defaults={
                    "category": category,
                    "description": f"{title} placeholder card for admin QA.",
                    "photo_alt": title,
                    "colors": "Black, Red",
                    "sizes": "S, M, L",
                    "sort_order": order,
                    "is_active": True,
                },
            )
            if not item.photo:
                item.photo.save(f"{slugify(title)}.png", self._image_file(), save=True)

        legal_pages = [
            ("demo-shipping-policy", "Demo Shipping Policy"),
            ("demo-return-policy", "Demo Return Policy"),
        ]
        for slug, title in legal_pages:
            LegalPage.objects.update_or_create(
                slug=slug,
                defaults={
                    "title": title,
                    "body": f"{title}\n\nThis is seeded demo copy used to test long legal content in admin.",
                    "is_active": True,
                },
            )

        for location, title in [
            (HeroImage.Location.HOME_GALLERY_D, "Demo Home Gallery Asset"),
            (HeroImage.Location.MERCH, "Demo Merch Hero"),
            (HeroImage.Location.PERFORMANCE_TUNING_GALLERY_C, "Demo Performance Detail"),
        ]:
            hero, created = HeroImage.objects.get_or_create(
                location=location,
                defaults={
                    "title": title,
                    "alt_text": title,
                    "caption": "Seeded for admin QA.",
                    "is_active": True,
                },
            )
            if created and not hero.image:
                hero.image.save(f"{slugify(title)}.png", self._image_file(), save=True)

        project_category = ProjectJournalCategory.objects.get_or_create(name="Demo Builds")[0]
        journal, _ = ProjectJournalEntry.objects.update_or_create(
            slug="demo-widebody-build",
            defaults={
                "title": "Demo Widebody Build",
                "headline": "Widebody + wheel package demo build",
                "excerpt": "Seeded journal entry with before/process/after media.",
                "overview": "A complete before/after demo build for QA walkthroughs.",
                "parts": "Widebody kit\nWheel package\nLighting upgrade",
                "customizations": "Panel fitment\nColor matching\nWheel fitment",
                "backstory": "Customer wanted a complete stance and lighting refresh.",
                "body": "This seeded entry exists so the journal admin, previews and category filters all have real content.",
                "client_name": "Demo Client",
                "location": "Edmonton",
                "services": "widebody,lighting,wheels",
                "result_highlight": "Aggressive stance with OEM-level fitment.",
                "status": ProjectJournalEntry.Status.PUBLISHED,
                "featured": True,
                "reading_time": 6,
                "cta_primary_label": "Book now",
                "cta_primary_url": "/services/",
                "cta_secondary_label": "Open store",
                "cta_secondary_url": "/store/",
            },
        )
        journal.categories.set([project_category])
        if not journal.cover_image:
            journal.cover_image.save("demo-widebody-build.png", self._image_file(), save=True)
        for kind, sort_order, alt_text in [
            (ProjectJournalPhoto.Kind.BEFORE, 10, "Demo build before"),
            (ProjectJournalPhoto.Kind.PROCESS, 20, "Demo build in process"),
            (ProjectJournalPhoto.Kind.AFTER, 30, "Demo build after"),
        ]:
            photo, _ = ProjectJournalPhoto.objects.update_or_create(
                entry=journal,
                kind=kind,
                sort_order=sort_order,
                defaults={"alt_text": alt_text},
            )
            if not photo.image:
                photo.image.save(f"demo-journal-{kind}-{sort_order}.png", self._image_file(), save=True)

        landing_specs = [
            (LandingPageReview.Page.HOME, "Demo Home Reviewer"),
            (LandingPageReview.Page.PERFORMANCE_TUNING, "Demo Performance Reviewer"),
            (LandingPageReview.Page.ELECTRICAL_WORK, "Demo Electrical Reviewer"),
            (LandingPageReview.Page.BRAKE_SUSPENSION, "Demo Suspension Reviewer"),
        ]
        for order, (page, reviewer_name) in enumerate(landing_specs, start=1):
            LandingPageReview.objects.update_or_create(
                page=page,
                reviewer_name=reviewer_name,
                defaults={
                    "reviewer_title": "QA sample",
                    "rating": 5 - (order % 2),
                    "quote": "Seeded review text to exercise testimonials, sorting and moderation views.",
                    "display_order": order * 10,
                    "is_published": True,
                },
            )

    def _seed_crm_and_leads(self, users: DemoUsers) -> None:
        approved, pending, rejected = users.dealers
        applications = [
            (
                approved,
                DealerApplication.Status.APPROVED,
                DealerTier.TIER_10,
                "Demo Offroad Supply",
            ),
            (
                pending,
                DealerApplication.Status.PENDING,
                DealerTier.TIER_5,
                "Demo Trail Partners",
            ),
            (
                rejected,
                DealerApplication.Status.REJECTED,
                DealerTier.NONE,
                "Demo Garage Wholesale",
            ),
        ]
        for user, status, preferred_tier, business_name in applications:
            application, _ = DealerApplication.objects.update_or_create(
                user=user,
                defaults={
                    "business_name": business_name,
                    "operating_as": business_name,
                    "business_address": "123 Demo Street",
                    "city": "Edmonton",
                    "province": "AB",
                    "postal_code": "T5J0N3",
                    "website": "https://example.com",
                    "phone": user.userprofile.phone,
                    "email": user.email,
                    "gst_tax_id": "GST-DEMO-123",
                    "business_license_number": "BL-2026-DEMO",
                    "years_in_business": 4,
                    "business_type": "Retail / Install shop",
                    "reference_1_name": "Demo Reference One",
                    "reference_1_phone": "+15551110001",
                    "reference_1_email": f"ref.one@{DEMO_DOMAIN}",
                    "reference_2_name": "Demo Reference Two",
                    "reference_2_phone": "+15551110002",
                    "reference_2_email": f"ref.two@{DEMO_DOMAIN}",
                    "authorized_signature_printed_name": user.get_full_name(),
                    "authorized_signature_title": "Owner",
                    "authorized_signature_date": self.today,
                    "notes": "Seeded application for admin QA.",
                    "preferred_tier": preferred_tier,
                    "assigned_tier": preferred_tier if status == DealerApplication.Status.APPROVED else "",
                    "internal_note": f"Demo application marked {status}.",
                    "status": status,
                    "reviewed_at": self.now - timedelta(days=1) if status != DealerApplication.Status.PENDING else None,
                    "reviewed_by": users.admin if status != DealerApplication.Status.PENDING else None,
                },
            )
            profile = user.userprofile
            profile.is_dealer = status == DealerApplication.Status.APPROVED
            profile.dealer_tier = preferred_tier if status == DealerApplication.Status.APPROVED else DealerTier.NONE
            profile.dealer_since = self.now - timedelta(days=30) if status == DealerApplication.Status.APPROVED else None
            profile.save(update_fields=["is_dealer", "dealer_tier", "dealer_since"])

        lead_specs = [
            ("Demo Lead One", "+15553330001", "Dyno tune", ServiceLead.SourcePage.PERFORMANCE_TUNING, ServiceLead.Status.NEW),
            ("Demo Lead Two", "+15553330002", "Lighting retrofit", ServiceLead.SourcePage.ELECTRICAL_WORK, ServiceLead.Status.CONTACTED),
            ("Demo Lead Three", "+15553330003", "Lift kit install", ServiceLead.SourcePage.BRAKE_SUSPENSION, ServiceLead.Status.CLOSED),
            ("Demo Lead Four", "+15553330004", "General build quote", ServiceLead.SourcePage.GENERAL_REQUEST, ServiceLead.Status.NEW),
        ]
        for idx, (full_name, phone, need, source_page, status) in enumerate(lead_specs, start=1):
            ServiceLead.objects.update_or_create(
                full_name=full_name,
                phone=phone,
                defaults={
                    "email": f"lead{idx}@{DEMO_DOMAIN}",
                    "vehicle": "2020 Ford F-150",
                    "service_needed": need,
                    "notes": "Seeded lead for admin QA.",
                    "source_page": source_page,
                    "source_url": f"https://demo.local/services/{slugify(need)}/",
                    "status": status,
                },
            )

        for idx, client in enumerate(users.clients[:3], start=1):
            file_record, _ = ClientFile.objects.get_or_create(
                user=client,
                description=f"Demo intake file #{idx}",
                defaults={"uploaded_by": ClientFile.ADMIN},
            )
            if not file_record.file:
                file_record.file.save(
                    f"demo-intake-{idx}.txt",
                    ContentFile(f"Demo intake file for {client.get_full_name()}".encode("utf-8")),
                    save=True,
                )

        LeadSubmissionEvent.objects.update_or_create(
            form_type=LeadSubmissionEvent.FormType.SERVICE_LEAD,
            outcome=LeadSubmissionEvent.Outcome.ACCEPTED,
            path="/services/performance-tuning/",
            defaults={
                "success": True,
                "suspicion_score": 6,
                "ip_address": "192.0.2.10",
                "ip_location": "Edmonton, CA",
                "user_agent": "Mozilla/5.0 Demo Browser",
                "accept_language": "en-CA,en;q=0.9",
                "referer": "https://demo.local/services/",
                "origin": "https://demo.local",
                "session_key_hash": "demo-session-service-lead",
                "time_on_page_ms": 142000,
                "cf_country": "CA",
                "cf_asn": "64500",
                "cf_asn_org": "Demo Telecom",
                "flags": {"honeypot": False, "velocity": "normal"},
            },
        )
        LeadSubmissionEvent.objects.update_or_create(
            form_type=LeadSubmissionEvent.FormType.FITMENT_REQUEST,
            outcome=LeadSubmissionEvent.Outcome.SUSPECTED,
            path="/store/p/demo-offroad-bumper/",
            defaults={
                "success": True,
                "suspicion_score": 62,
                "validation_errors": "Disposable email domain flagged.",
                "ip_address": "198.51.100.24",
                "ip_location": "Calgary, CA",
                "user_agent": "Mozilla/5.0 Demo Browser",
                "accept_language": "en-US,en;q=0.8",
                "referer": "https://demo.local/store/",
                "origin": "https://demo.local",
                "session_key_hash": "demo-session-fitment",
                "time_on_page_ms": 67000,
                "cf_country": "CA",
                "cf_asn": "64501",
                "cf_asn_org": "Demo Wireless",
                "flags": {"velocity": "medium", "captcha": "pass"},
            },
        )

    def _seed_appointments_and_payments(self, users: DemoUsers, refs: dict) -> None:
        next_monday = self._next_weekday(self.today, 0)
        next_tuesday = self._next_weekday(self.today, 1)
        next_thursday = self._next_weekday(self.today, 3)
        next_saturday = self._next_weekday(self.today, 5)

        BookingDayOverride.objects.update_or_create(
            date=next_saturday,
            defaults={"status": BookingDayOverride.Status.OPEN, "note": "Demo open Saturday for calendar QA."},
        )
        BookingDayOverride.objects.update_or_create(
            date=next_thursday + timedelta(days=1),
            defaults={"status": BookingDayOverride.Status.CLOSED, "note": "Demo forced closure."},
        )

        availability_specs = [
            (users.masters[0], self._aware(next_monday, 12, 0), self._aware(next_monday, 12, 45), MasterAvailability.LUNCH),
            (users.masters[1], self._aware(next_tuesday, 15, 0), self._aware(next_tuesday, 16, 30), MasterAvailability.BREAK),
            (users.masters[2], self._aware(next_thursday, 10, 0), self._aware(next_thursday, 12, 0), MasterAvailability.VACATION),
        ]
        for master, start_time, end_time, reason in availability_specs:
            MasterAvailability.objects.update_or_create(
                master=master,
                start_time=start_time,
                end_time=end_time,
                defaults={"reason": reason},
            )

        appointments = [
            {
                "label": "future_paid",
                "client": users.clients[0],
                "contact_name": users.clients[0].get_full_name(),
                "contact_email": users.clients[0].email,
                "contact_phone": users.clients[0].userprofile.phone,
                "master": users.masters[0],
                "service": refs["services"]["dyno"],
                "start_time": self._aware(next_monday, 9, 0),
                "payment_status": refs["payment_statuses"]["Paid"],
                "statuses": ["Scheduled", "Confirmed"],
                "payment": {
                    "amount": Decimal("650.00"),
                    "method": refs["payment_methods"]["Card"],
                    "mode": Payment.PaymentMode.FULL,
                    "processor_payment_id": "demo-appt-paid-01",
                    "processor": "stripe",
                    "receipt_url": "https://example.com/receipt/demo-appt-paid-01",
                },
            },
            {
                "label": "future_guest_estimate",
                "client": None,
                "contact_name": "Demo Guest Walker",
                "contact_email": f"guest.walker@{DEMO_DOMAIN}",
                "contact_phone": "+15554440001",
                "master": users.masters[0],
                "service": refs["services"]["estimate"],
                "start_time": self._aware(next_monday, 10, 45),
                "payment_status": refs["payment_statuses"]["Unpaid"],
                "statuses": ["Scheduled"],
            },
            {
                "label": "future_deposit",
                "client": users.clients[1],
                "contact_name": users.clients[1].get_full_name(),
                "contact_email": users.clients[1].email,
                "contact_phone": users.clients[1].userprofile.phone,
                "master": users.masters[1],
                "service": refs["services"]["lighting"],
                "start_time": self._aware(next_monday, 13, 15),
                "payment_status": refs["payment_statuses"]["Pending"],
                "statuses": ["Scheduled", "Confirmed"],
                "prepayment": refs["prepayments"][25],
                "payment": {
                    "amount": Decimal("105.00"),
                    "method": refs["payment_methods"]["Stripe"],
                    "mode": Payment.PaymentMode.DEPOSIT_50,
                    "balance_due": Decimal("315.00"),
                    "processor_payment_id": "demo-appt-deposit-01",
                    "processor": "stripe",
                    "card_brand": "visa",
                    "card_last4": "4242",
                },
            },
            {
                "label": "future_cancelled",
                "client": users.clients[2],
                "contact_name": users.clients[2].get_full_name(),
                "contact_email": users.clients[2].email,
                "contact_phone": users.clients[2].userprofile.phone,
                "master": users.masters[1],
                "service": refs["services"]["diag"],
                "start_time": self._aware(next_tuesday, 9, 30),
                "payment_status": refs["payment_statuses"]["Unpaid"],
                "statuses": ["Scheduled", "Cancelled"],
            },
            {
                "label": "future_no_show",
                "client": users.clients[3],
                "contact_name": users.clients[3].get_full_name(),
                "contact_email": users.clients[3].email,
                "contact_phone": users.clients[3].userprofile.phone,
                "master": users.masters[2],
                "service": refs["services"]["alignment"],
                "start_time": self._aware(next_tuesday, 11, 0),
                "payment_status": refs["payment_statuses"]["Unpaid"],
                "statuses": ["Scheduled", "No Show"],
            },
            {
                "label": "past_completed_reviewed",
                "client": users.clients[4],
                "contact_name": users.clients[4].get_full_name(),
                "contact_email": users.clients[4].email,
                "contact_phone": users.clients[4].userprofile.phone,
                "master": users.masters[0],
                "service": refs["services"]["lift"],
                "start_time": self._aware(self.today - timedelta(days=1), 14, 0),
                "payment_status": refs["payment_statuses"]["Paid"],
                "statuses": ["Scheduled", "In Progress", "Completed"],
                "payment": {
                    "amount": Decimal("980.00"),
                    "method": refs["payment_methods"]["Card"],
                    "mode": Payment.PaymentMode.FULL,
                    "processor_payment_id": "demo-appt-paid-02",
                    "processor": "stripe",
                    "card_brand": "mastercard",
                    "card_last4": "4444",
                },
                "review": (5, "Truck rides cleaner than expected after the seeded demo install."),
            },
            {
                "label": "past_completed_promo",
                "client": users.clients[5],
                "contact_name": users.clients[5].get_full_name(),
                "contact_email": users.clients[5].email,
                "contact_phone": users.clients[5].userprofile.phone,
                "master": users.masters[1],
                "service": refs["services"]["dyno"],
                "start_time": self._aware(self.today - timedelta(days=2), 9, 45),
                "payment_status": refs["payment_statuses"]["Paid"],
                "statuses": ["Scheduled", "Completed"],
                "promo": refs["service_code"],
                "payment": {
                    "amount": Decimal("552.50"),
                    "method": refs["payment_methods"]["E-Transfer"],
                    "mode": Payment.PaymentMode.FULL,
                    "processor_payment_id": "demo-appt-paid-03",
                    "processor": "etransfer",
                },
            },
            {
                "label": "weekend_open",
                "client": users.clients[6],
                "contact_name": users.clients[6].get_full_name(),
                "contact_email": users.clients[6].email,
                "contact_phone": users.clients[6].userprofile.phone,
                "master": users.masters[2],
                "service": refs["services"]["lighting"],
                "start_time": self._aware(next_saturday, 11, 0),
                "payment_status": refs["payment_statuses"]["Pending"],
                "statuses": ["Scheduled", "Confirmed"],
                "prepayment": refs["prepayments"][25],
            },
            {
                "label": "future_prepay_due",
                "client": users.clients[7],
                "contact_name": users.clients[7].get_full_name(),
                "contact_email": users.clients[7].email,
                "contact_phone": users.clients[7].userprofile.phone,
                "master": users.masters[0],
                "service": refs["services"]["dyno"],
                "start_time": self._aware(next_thursday, 15, 30),
                "payment_status": refs["payment_statuses"]["Pending"],
                "statuses": ["Scheduled", "Confirmed"],
                "prepayment": refs["prepayments"][50],
            },
            {
                "label": "past_guest_paid",
                "client": None,
                "contact_name": "Demo Guest Alvarez",
                "contact_email": f"guest.alvarez@{DEMO_DOMAIN}",
                "contact_phone": "+15554440002",
                "master": users.masters[1],
                "service": refs["services"]["diag"],
                "start_time": self._aware(self.today - timedelta(days=3), 16, 0),
                "payment_status": refs["payment_statuses"]["Paid"],
                "statuses": ["Scheduled", "Completed"],
                "payment": {
                    "amount": Decimal("180.00"),
                    "method": refs["payment_methods"]["Cash"],
                    "mode": Payment.PaymentMode.FULL,
                    "processor_payment_id": "demo-appt-paid-04",
                    "processor": "cash",
                },
                "review": (4, "Quick diagnosis and clear explanation."),
            },
        ]

        created_appts = {}
        for spec in appointments:
            appointment, _ = Appointment.objects.update_or_create(
                master=spec["master"],
                service=spec["service"],
                start_time=spec["start_time"],
                defaults={
                    "client": spec["client"],
                    "contact_name": spec["contact_name"],
                    "contact_email": spec["contact_email"],
                    "contact_phone": spec["contact_phone"],
                    "payment_status": spec["payment_status"],
                },
            )
            created_appts[spec["label"]] = appointment

            AppointmentStatusHistory.objects.filter(appointment=appointment).delete()
            for idx, status_name in enumerate(spec["statuses"], start=1):
                AppointmentStatusHistory.objects.create(
                    appointment=appointment,
                    status=refs["appointment_statuses"][status_name],
                    set_by=users.admin if idx < len(spec["statuses"]) else appointment.master,
                )

            AppointmentPrepayment.objects.filter(appointment=appointment).delete()
            if spec.get("prepayment"):
                AppointmentPrepayment.objects.update_or_create(
                    appointment=appointment,
                    defaults={"option": spec["prepayment"]},
                )

            AppointmentPromoCode.objects.filter(appointment=appointment).delete()
            if spec.get("promo"):
                AppointmentPromoCode.objects.update_or_create(
                    appointment=appointment,
                    defaults={
                        "promocode": spec["promo"],
                        "discount_applied": Decimal("97.50"),
                    },
                )

            Payment.objects.filter(appointment=appointment, order__isnull=True).exclude(
                processor_payment_id__startswith="demo-order-"
            ).delete()
            if spec.get("payment"):
                payment_defaults = {
                    "appointment": appointment,
                    "amount": spec["payment"]["amount"],
                    "currency": "CAD",
                    "method": spec["payment"]["method"],
                    "payment_mode": spec["payment"]["mode"],
                    "balance_due": spec["payment"].get("balance_due", Decimal("0.00")),
                    "processor": spec["payment"].get("processor", ""),
                    "receipt_url": spec["payment"].get("receipt_url", ""),
                    "card_brand": spec["payment"].get("card_brand", ""),
                    "card_last4": spec["payment"].get("card_last4", ""),
                    "fee_amount": Decimal("0.00"),
                }
                Payment.objects.update_or_create(
                    processor_payment_id=spec["payment"]["processor_payment_id"],
                    defaults=payment_defaults,
                )

            if spec.get("review"):
                rating, comment = spec["review"]
                AppointmentReview.objects.update_or_create(
                    appointment=appointment,
                    defaults={"rating": rating, "comment": comment},
                )

        Notification.objects.update_or_create(
            user=users.clients[0],
            appointment=created_appts["future_paid"],
            channel="email",
            message="Demo reminder: your dyno tune is booked and fully paid.",
        )
        Notification.objects.update_or_create(
            user=users.clients[1],
            appointment=created_appts["future_deposit"],
            channel="sms",
            message="Demo deposit reminder: remaining balance is due on arrival.",
        )

    def _seed_store(self, users: DemoUsers, refs: dict) -> None:
        pricing = StorePricingSettings.load() or StorePricingSettings.objects.create(price_multiplier_percent=108)
        if pricing.price_multiplier_percent <= 0:
            pricing.price_multiplier_percent = 108
            pricing.save(update_fields=["price_multiplier_percent"])
        shipping = StoreShippingSettings.load() or StoreShippingSettings.objects.create(
            free_shipping_threshold_cad=Decimal("350.00"),
            delivery_cost_under_threshold_cad=Decimal("25.00"),
        )
        inventory = StoreInventorySettings.load() or StoreInventorySettings.objects.create(
            low_stock_threshold=4,
            allow_out_of_stock_orders=False,
        )
        if shipping.free_shipping_threshold_cad in (None, Decimal("0.00")):
            shipping.free_shipping_threshold_cad = Decimal("350.00")
            shipping.delivery_cost_under_threshold_cad = Decimal("25.00")
            shipping.save(update_fields=["free_shipping_threshold_cad", "delivery_cost_under_threshold_cad"])
        if inventory.low_stock_threshold == 0:
            inventory.low_stock_threshold = 4
            inventory.allow_out_of_stock_orders = False
            inventory.save(update_fields=["low_stock_threshold", "allow_out_of_stock_orders"])

        import_batch, _ = ImportBatch.objects.update_or_create(
            source_filename="demo_catalog_refresh.csv",
            defaults={
                "created_by": users.admin,
                "mode": "append",
                "is_dry_run": False,
                "created_products": 4,
                "updated_products": 6,
                "created_options": 10,
                "updated_options": 3,
                "created_categories": 2,
                "error_count": 1,
            },
        )
        cleanup_batch, _ = CleanupBatch.objects.update_or_create(
            criteria="demo-placeholder-cleanup",
            defaults={
                "created_by": users.coordinator,
                "matched_products": 3,
                "deactivated_products": 2,
            },
        )

        categories = {
            "armor": Category.objects.get_or_create(name="Demo Armor", defaults={"slug": "demo-armor"})[0],
            "lighting": Category.objects.get_or_create(name="Demo Lighting", defaults={"slug": "demo-lighting"})[0],
            "suspension": Category.objects.get_or_create(name="Demo Suspension", defaults={"slug": "demo-suspension"})[0],
        }
        merch_categories = {
            "apparel": MerchCategory.objects.get_or_create(name="Demo Apparel")[0],
            "accessories": MerchCategory.objects.get_or_create(name="Demo Accessories")[0],
        }
        make = CarMake.objects.get_or_create(name="Demo Motors")[0]
        models = [
            CarModel.objects.get_or_create(make=make, name="Trail Runner", defaults={"year_from": 2018, "year_to": 2024})[0],
            CarModel.objects.get_or_create(make=make, name="City Cruiser", defaults={"year_from": 2016, "year_to": 2023})[0],
        ]

        products = {
            "bumper": self._upsert_product(
                sku="DEMO-BUMPER-001",
                name="Demo Offroad Bumper",
                category=categories["armor"],
                merch_category=None,
                price=Decimal("899.00"),
                inventory=6,
                import_batch=import_batch,
                description="Seeded product with options, discount and gallery.",
                compatible_models=models,
            ),
            "lightbar": self._upsert_product(
                sku="DEMO-LIGHT-001",
                name="Demo Roof Light Bar",
                category=categories["lighting"],
                merch_category=None,
                price=Decimal("349.00"),
                inventory=2,
                description="Low-stock demo product.",
                compatible_models=models[:1],
            ),
            "liftkit": self._upsert_product(
                sku="DEMO-LIFT-001",
                name="Demo 4in Lift Kit",
                category=categories["suspension"],
                merch_category=None,
                price=Decimal("1299.00"),
                inventory=0,
                description="Out-of-stock demo product.",
                compatible_models=models[:1],
            ),
            "merchtee": self._upsert_product(
                sku="DEMO-MERCH-TEE-001",
                name="Demo Shop Tee",
                category=categories["armor"],
                merch_category=merch_categories["apparel"],
                price=Decimal("34.00"),
                inventory=18,
                description="Merch product wired to merch category.",
                is_in_house=False,
            ),
            "estimate": self._upsert_product(
                sku="DEMO-CUSTOM-001",
                name="Demo Custom Build Intake",
                category=categories["suspension"],
                merch_category=merch_categories["accessories"],
                price=Decimal("0.00"),
                inventory=1,
                description="Estimate-only seeded listing.",
                contact_for_estimate=True,
                estimate_from_price=Decimal("450.00"),
            ),
        }

        ProductDiscount.objects.update_or_create(
            product=products["bumper"],
            discount_percent=12,
            defaults={"start_date": self.today - timedelta(days=2), "end_date": self.today + timedelta(days=18)},
        )
        ProductDiscount.objects.update_or_create(
            product=products["merchtee"],
            discount_percent=20,
            defaults={"start_date": self.today - timedelta(days=1), "end_date": self.today + timedelta(days=7)},
        )

        for product, option_specs in [
            (products["bumper"], [("Standard finish", Decimal("899.00"), True, False), ("Powder coat", Decimal("949.00"), True, False)]),
            (products["lightbar"], [("30 inch", Decimal("349.00"), True, False), ("40 inch", Decimal("419.00"), True, False)]),
            (products["merchtee"], [("Small", Decimal("34.00"), True, False), ("Large", Decimal("34.00"), True, False), ("Archive", None, False, False)]),
        ]:
            for sort_order, (name, price, is_active, is_separator) in enumerate(option_specs, start=10):
                ProductOption.objects.update_or_create(
                    product=product,
                    name=name,
                    defaults={
                        "sku": f"{product.sku}-{slugify(name).upper()}",
                        "description": f"Demo option {name}",
                        "price": price,
                        "is_active": is_active,
                        "is_separator": is_separator,
                        "sort_order": sort_order,
                    },
                )

        for product in [products["bumper"], products["lightbar"], products["merchtee"]]:
            if not product.main_image:
                product.main_image.save(f"{product.sku.lower()}.png", self._image_file(), save=True)
            for idx in range(1, 3):
                image, _ = ProductImage.objects.get_or_create(
                    product=product,
                    alt=f"Demo gallery shot {idx} for {product.name}",
                    defaults={"sort_order": idx * 10},
                )
                if not image.image:
                    image.image.save(f"{product.sku.lower()}-gallery-{idx}.png", self._image_file(), save=True)

        product_code = PromoCode.objects.get_or_create(
            code="DEMO-PRODUCT-10",
            defaults={
                "discount_percent": 10,
                "active": True,
                "start_date": self.today - timedelta(days=3),
                "end_date": self.today + timedelta(days=30),
                "applies_to_services": False,
                "applies_to_products": True,
            },
        )[0]
        product_code.applicable_products.set([products["bumper"], products["merchtee"]])

        orders = [
            {
                "email": f"order.processing@{DEMO_DOMAIN}",
                "customer_name": "Demo Order Processing",
                "user": users.clients[0],
                "status": Order.STATUS_PROCESSING,
                "payment_status": Order.PaymentStatus.PAID,
                "payment_mode": Order.PaymentMode.DEPOSIT,
                "payment_amount": Decimal("250.00"),
                "payment_balance_due": Decimal("249.00"),
                "items": [(products["bumper"], None, 1), (products["lightbar"], None, 1)],
            },
            {
                "email": f"order.shipped@{DEMO_DOMAIN}",
                "customer_name": "Demo Order Shipped",
                "user": users.dealers[0],
                "status": Order.STATUS_SHIPPED,
                "payment_status": Order.PaymentStatus.PAID,
                "payment_mode": Order.PaymentMode.FULL,
                "payment_amount": Decimal("34.00"),
                "payment_balance_due": Decimal("0.00"),
                "tracking_numbers": "DEMO123456789",
                "tracking_url": "https://example.com/tracking/DEMO123456789",
                "items": [(products["merchtee"], ProductOption.objects.filter(product=products["merchtee"], name="Large").first(), 2)],
                "promo": product_code,
            },
            {
                "email": f"order.completed@{DEMO_DOMAIN}",
                "customer_name": "Demo Order Completed",
                "user": users.clients[2],
                "status": Order.STATUS_COMPLETED,
                "payment_status": Order.PaymentStatus.PAID,
                "payment_mode": Order.PaymentMode.FULL,
                "payment_amount": Decimal("419.00"),
                "payment_balance_due": Decimal("0.00"),
                "items": [(products["lightbar"], ProductOption.objects.filter(product=products["lightbar"], name="40 inch").first(), 1)],
            },
            {
                "email": f"order.cancelled@{DEMO_DOMAIN}",
                "customer_name": "Demo Order Cancelled",
                "user": users.clients[3],
                "status": Order.STATUS_CANCELLED,
                "payment_status": Order.PaymentStatus.FAILED,
                "payment_mode": Order.PaymentMode.FULL,
                "payment_amount": Decimal("0.00"),
                "payment_balance_due": Decimal("0.00"),
                "items": [(products["liftkit"], None, 1)],
            },
            {
                "email": f"order.unpaid@{DEMO_DOMAIN}",
                "customer_name": "Demo Order Unpaid",
                "user": None,
                "status": Order.STATUS_PROCESSING,
                "payment_status": Order.PaymentStatus.UNPAID,
                "payment_mode": Order.PaymentMode.FULL,
                "payment_amount": Decimal("0.00"),
                "payment_balance_due": Decimal("450.00"),
                "items": [(products["estimate"], None, 1)],
            },
        ]

        saved_orders = []
        for spec in orders:
            order, _ = Order.objects.update_or_create(
                email=spec["email"],
                defaults={
                    "user": spec["user"],
                    "customer_name": spec["customer_name"],
                    "phone": "+15556667777",
                    "delivery_method": "shipping",
                    "address_line1": "987 Demo Ave",
                    "city": "Edmonton",
                    "region": "AB",
                    "postal_code": "T5J0N3",
                    "country": "Canada",
                    "vehicle_make": "Demo Motors",
                    "vehicle_model": "Trail Runner",
                    "vehicle_year": 2022,
                    "notes": "Seeded order for admin QA.",
                    "status": spec["status"],
                    "payment_status": spec["payment_status"],
                    "payment_mode": spec["payment_mode"],
                    "payment_amount": spec["payment_amount"],
                    "payment_balance_due": spec["payment_balance_due"],
                    "payment_processor": "stripe" if spec["payment_status"] == Order.PaymentStatus.PAID else "",
                    "payment_id": f"demo-order-{slugify(spec['customer_name'])}",
                    "payment_receipt_url": "https://example.com/receipt/demo-order",
                    "tracking_numbers": spec.get("tracking_numbers", ""),
                    "tracking_url": spec.get("tracking_url", ""),
                    "shipping_cost": Decimal("25.00"),
                    "printful_status": "fulfilled" if spec["status"] == Order.STATUS_SHIPPED else "pending",
                },
            )
            saved_orders.append(order)
            for product, option, qty in spec["items"]:
                OrderItem.objects.update_or_create(
                    order=order,
                    product=product,
                    option=option,
                    defaults={"qty": qty, "price_at_moment": product.get_unit_price(option)},
                )
            Payment.objects.filter(order=order, appointment__isnull=True).exclude(
                processor_payment_id__startswith="demo-order-"
            ).delete()
            if spec["payment_status"] == Order.PaymentStatus.PAID:
                Payment.objects.update_or_create(
                    processor_payment_id=f"demo-order-{order.pk}",
                    defaults={
                        "order": order,
                        "amount": spec["payment_amount"],
                        "currency": "CAD",
                        "method": refs["payment_methods"]["Card"],
                        "payment_mode": Payment.PaymentMode.DEPOSIT_50 if spec["payment_mode"] == Order.PaymentMode.DEPOSIT else Payment.PaymentMode.FULL,
                        "balance_due": spec["payment_balance_due"],
                        "processor": "stripe",
                        "receipt_url": order.payment_receipt_url,
                        "card_brand": "visa",
                        "card_last4": "4242",
                    },
                )
            if spec.get("promo"):
                OrderPromoCode.objects.update_or_create(
                    order=order,
                    defaults={
                        "promocode": spec["promo"],
                        "discount_percent": 10,
                        "discount_amount": Decimal("6.80"),
                    },
                )

        fitment_specs = [
            ("Demo Fitment One", CustomFitmentRequest.Status.NEW, products["bumper"]),
            ("Demo Fitment Two", CustomFitmentRequest.Status.IN_PROGRESS, products["lightbar"]),
            ("Demo Fitment Three", CustomFitmentRequest.Status.RESPONDED, products["estimate"]),
        ]
        for idx, (customer_name, status, product) in enumerate(fitment_specs, start=1):
            CustomFitmentRequest.objects.update_or_create(
                customer_name=customer_name,
                email=f"fitment{idx}@{DEMO_DOMAIN}",
                defaults={
                    "product": product,
                    "product_name": product.name,
                    "phone": f"+1555777000{idx}",
                    "vehicle": "2021 Demo Motors Trail Runner",
                    "submodel": "XLT",
                    "performance_goals": "Weekend overland build",
                    "budget": "$3k-$5k",
                    "timeline": "Within 6 weeks",
                    "message": "Seeded fitment request for admin QA.",
                    "source_url": f"https://demo.local/store/p/{product.slug}/",
                    "status": status,
                },
            )

        reviews = [
            ("Demo Store Review Pending", StoreReview.Status.PENDING, products["lightbar"], 4),
            ("Demo Store Review Approved", StoreReview.Status.APPROVED, products["bumper"], 5),
            ("Demo Store Review Rejected", StoreReview.Status.REJECTED, None, 2),
        ]
        for idx, (title, status, product, rating) in enumerate(reviews, start=1):
            StoreReview.objects.update_or_create(
                reviewer_email=f"review{idx}@{DEMO_DOMAIN}",
                defaults={
                    "product": product,
                    "user": users.clients[min(idx - 1, len(users.clients) - 1)],
                    "reviewer_name": title,
                    "reviewer_title": "QA sample",
                    "rating": rating,
                    "title": title,
                    "body": "Seeded review copy to exercise moderation states and product-linked reviews.",
                    "source_url": "https://demo.local/store/",
                    "status": status,
                    "approved_at": self.now - timedelta(days=1) if status == StoreReview.Status.APPROVED else None,
                    "approved_by": users.admin if status == StoreReview.Status.APPROVED else None,
                },
            )

        PrintfulWebhookEvent.objects.update_or_create(
            event_hash="demo-printful-event-001",
            defaults={
                "event_type": "package_shipped",
                "order": saved_orders[1],
                "payload": {"tracking_number": "DEMO123456789", "status": "shipped"},
            },
        )

        AbandonedCart.objects.update_or_create(
            email=f"abandoned@{DEMO_DOMAIN}",
            defaults={
                "user": users.clients[4],
                "session_key": "demo-abandoned-cart-1",
                "cart_items": [{"sku": products["merchtee"].sku, "qty": 2}],
                "cart_total": Decimal("68.00"),
                "currency_code": "CAD",
                "currency_symbol": "$",
                "last_activity_at": self.now - timedelta(hours=5),
            },
        )

    def _seed_email_and_telegram(self, users: DemoUsers) -> None:
        subscribers = [
            ("newsletter.one", EmailSubscriber.Source.MANUAL, True),
            ("newsletter.two", EmailSubscriber.Source.IMPORT, True),
            ("newsletter.three", EmailSubscriber.Source.MANUAL, False),
        ]
        for local_part, source, active in subscribers:
            EmailSubscriber.objects.update_or_create(
                email=f"{local_part}@{DEMO_DOMAIN}",
                defaults={
                    "source": source,
                    "is_active": active,
                    "added_by": users.admin,
                },
            )

        campaigns = [
            ("Demo Spring Campaign", EmailCampaign.Status.DRAFT),
            ("Demo Partial Send", EmailCampaign.Status.PARTIAL),
            ("Demo Sent Campaign", EmailCampaign.Status.SENT),
        ]
        created_campaigns = []
        for idx, (name, status) in enumerate(campaigns, start=1):
            campaign, _ = EmailCampaign.objects.update_or_create(
                name=name,
                defaults={
                    "status": status,
                    "from_email": "ops@demo.local",
                    "subject": f"{name} Subject",
                    "preheader": "Seeded preheader for admin QA.",
                    "title": name,
                    "greeting": "Hello from demo seed",
                    "intro": "Line one\nLine two",
                    "notice_title": "Demo notice",
                    "notice": "Watch statuses\nVerify filters",
                    "footer": "Thanks\nDemo Team",
                    "cta_label": "Open site",
                    "cta_url": "https://demo.local/",
                    "include_subscribers": True,
                    "include_registered_users": True,
                    "recipients_total": 3,
                    "sent_count": 2 if status != EmailCampaign.Status.DRAFT else 0,
                    "failed_count": 1 if status == EmailCampaign.Status.PARTIAL else 0,
                    "send_started_at": self.now - timedelta(days=idx) if status != EmailCampaign.Status.DRAFT else None,
                    "send_completed_at": self.now - timedelta(days=idx, minutes=-5) if status in {EmailCampaign.Status.PARTIAL, EmailCampaign.Status.SENT} else None,
                    "sent_by": users.coordinator if status != EmailCampaign.Status.DRAFT else None,
                },
            )
            created_campaigns.append(campaign)

        recipient_statuses = [
            EmailCampaignRecipient.Status.PENDING,
            EmailCampaignRecipient.Status.SENT,
            EmailCampaignRecipient.Status.FAILED,
            EmailCampaignRecipient.Status.SKIPPED,
        ]
        for idx, recipient_status in enumerate(recipient_statuses, start=1):
            EmailCampaignRecipient.objects.update_or_create(
                campaign=created_campaigns[1],
                email=f"campaign.recipient.{idx}@{DEMO_DOMAIN}",
                defaults={
                    "user": users.clients[idx - 1] if idx <= len(users.clients) else None,
                    "source": EmailCampaignRecipient.Source.USER if idx % 2 else EmailCampaignRecipient.Source.SUBSCRIBER,
                    "status": recipient_status,
                    "error_message": "Mailbox full" if recipient_status == EmailCampaignRecipient.Status.FAILED else "",
                    "sent_at": self.now - timedelta(hours=idx) if recipient_status == EmailCampaignRecipient.Status.SENT else None,
                },
            )

        EmailSendLog.objects.update_or_create(
            email_type="demo_campaign_send",
            subject="Demo campaign log",
            defaults={
                "from_email": "ops@demo.local",
                "recipients": [f"log.one@{DEMO_DOMAIN}", f"log.two@{DEMO_DOMAIN}"],
                "recipient_count": 2,
                "success": True,
                "error_message": "",
            },
        )
        EmailSendLog.objects.update_or_create(
            email_type="demo_failed_send",
            subject="Demo failed email",
            defaults={
                "from_email": "ops@demo.local",
                "recipients": [f"log.fail@{DEMO_DOMAIN}"],
                "recipient_count": 1,
                "success": False,
                "error_message": "SMTP timeout in seeded example.",
            },
        )

        bot_settings = TelegramBotSettings.load() or TelegramBotSettings.objects.create(
            name="Demo Operations Bot",
            enabled=False,
            admin_chat_ids="10001 10002",
        )
        if not bot_settings.name.startswith("Demo"):
            bot_settings.name = "Demo Operations Bot"
            bot_settings.enabled = False
            bot_settings.admin_chat_ids = "10001 10002"
            bot_settings.notify_on_new_appointment = True
            bot_settings.notify_on_new_order = True
            bot_settings.digest_enabled = True
            bot_settings.digest_hour_local = 8
            bot_settings.save()

        for chat_id, label in [(10001, "Demo Ops"), (10002, "Demo Sales")]:
            TelegramRecipientSlot.objects.update_or_create(
                settings=bot_settings,
                chat_id=chat_id,
                defaults={"label": label},
            )

        contacts = []
        for name, chat_id in [("Demo Alex Telegram", 20001), ("Demo Bri Telegram", 20002), ("Demo Client Telegram", 20003)]:
            contact, _ = TelegramContact.objects.update_or_create(
                chat_id=chat_id,
                defaults={"name": name, "notes": "Seeded telegram contact."},
            )
            contacts.append(contact)

        for event_type, chat_id, success in [
            (TelegramMessageLog.EVENT_APPOINTMENT_CREATED, 10001, True),
            (TelegramMessageLog.EVENT_ORDER_CREATED, 10002, True),
            (TelegramMessageLog.EVENT_SERVICE_LEAD, 10001, False),
        ]:
            TelegramMessageLog.objects.update_or_create(
                event_type=event_type,
                chat_id=chat_id,
                payload=f"Seeded payload for {event_type}",
                defaults={
                    "success": success,
                    "error_message": "" if success else "Seeded API timeout",
                },
            )

        pending_reminder, _ = TelegramReminder.objects.update_or_create(
            title="Demo Pending Reminder",
            defaults={
                "message": "Follow up on unpaid appointments.",
                "scheduled_for": self.now + timedelta(hours=6),
                "target_chat_ids": "10001",
                "status": TelegramReminder.Status.PENDING,
            },
        )
        pending_reminder.contacts.set(contacts[:2])

        sent_reminder, _ = TelegramReminder.objects.update_or_create(
            title="Demo Sent Reminder",
            defaults={
                "message": "Daily digest was sent.",
                "scheduled_for": self.now - timedelta(hours=3),
                "target_chat_ids": "10002",
                "status": TelegramReminder.Status.SENT,
                "sent_at": self.now - timedelta(hours=2),
            },
        )
        sent_reminder.contacts.set([contacts[2]])

    def _seed_analytics_and_logs(self, users: DemoUsers) -> None:
        for idx, (status, trigger) in enumerate(
            [
                (ClientUiCheckRun.Status.SUCCESS, ClientUiCheckRun.Trigger.MANUAL),
                (ClientUiCheckRun.Status.WARNING, ClientUiCheckRun.Trigger.AUTO),
                (ClientUiCheckRun.Status.FAILED, ClientUiCheckRun.Trigger.MANUAL),
            ],
            start=1,
        ):
            ClientUiCheckRun.objects.update_or_create(
                summary=f"Demo UI check run #{idx}",
                defaults={
                    "trigger": trigger,
                    "status": status,
                    "finished_at": self.now - timedelta(hours=idx),
                    "duration_ms": 35000 + idx * 1200,
                    "total_pages": 24,
                    "total_links": 132,
                    "total_forms": 11,
                    "total_buttons": 84,
                    "failures_count": 0 if status == ClientUiCheckRun.Status.SUCCESS else idx,
                    "warnings_count": idx,
                    "skipped_count": 1 if status == ClientUiCheckRun.Status.WARNING else 0,
                    "report": {"demo_seed": True, "run": idx, "status": status},
                    "triggered_by": users.admin if trigger == ClientUiCheckRun.Trigger.MANUAL else None,
                },
            )

        session_specs = [
            ("demo-session-001", None, "/"),
            ("demo-session-002", users.clients[0], "/store/"),
            ("demo-session-003", users.dealers[0], "/client-portal/"),
        ]
        for idx, (session_key, user, landing_path) in enumerate(session_specs, start=1):
            session, _ = VisitorSession.objects.update_or_create(
                session_key=session_key,
                defaults={
                    "user": user,
                    "user_email_snapshot": getattr(user, "email", ""),
                    "user_name_snapshot": user.get_full_name() if user else "Anonymous Demo Visitor",
                    "ip_address": f"203.0.113.{idx}",
                    "ip_location": "Edmonton, CA",
                    "user_agent": "Mozilla/5.0 Demo Browser",
                    "referrer": "https://google.com/",
                    "landing_path": landing_path,
                    "landing_query": "utm_source=demo-seed",
                },
            )
            for view_index, path in enumerate(
                [landing_path, "/store/p/demo-offroad-bumper/", "/legal/demo-shipping-policy/"],
                start=1,
            ):
                PageView.objects.update_or_create(
                    page_instance_id=f"{session_key}-pv-{view_index}",
                    defaults={
                        "session": session,
                        "user": user,
                        "path": path,
                        "full_path": f"https://demo.local{path}",
                        "page_title": f"Demo Page {view_index}",
                        "referrer": "https://demo.local/",
                        "started_at": self.now - timedelta(minutes=view_index * 7),
                        "duration_ms": 15000 * view_index,
                        "timezone_offset": -360,
                        "viewport_width": 1440,
                        "viewport_height": 900,
                    },
                )

        for idx, staff_user in enumerate([users.admin, users.coordinator] + users.masters, start=1):
            StaffLoginEvent.objects.update_or_create(
                user=staff_user,
                session_key=f"demo-staff-login-{idx}",
                defaults={
                    "logged_in_at": self.now - timedelta(hours=idx * 3),
                    "ip_address": f"198.18.0.{idx}",
                    "ip_location": "Edmonton, CA",
                    "user_agent": "Mozilla/5.0 Demo Staff Browser",
                    "login_path": "/admin/login/",
                },
            )

        sidebar_seen_rows = [
            (users.admin, "core", "appointment"),
            (users.admin, "store", "product"),
            (users.masters[0], "core", "appointment"),
            (users.coordinator, "core", "servicelead"),
        ]
        for user, app_label, model_name in sidebar_seen_rows:
            AdminSidebarSeen.objects.update_or_create(
                user=user,
                app_label=app_label,
                model_name=model_name,
                defaults={"last_seen_at": self.now - timedelta(hours=2)},
            )

        signups = [
            ("notice.one", 0, 1),
            ("notice.two", 2, 0),
            ("notice.three", 5, 4),
        ]
        for local_part, followup_2_days, followup_3_days in signups:
            SiteNoticeSignup.objects.update_or_create(
                email=f"{local_part}@{DEMO_DOMAIN}",
                defaults={
                    "welcome_code": f"DEMO-{slugify(local_part).upper()}",
                    "welcome_sent_at": self.now - timedelta(days=7),
                    "followup_2_sent_at": self.now - timedelta(days=followup_2_days) if followup_2_days else None,
                    "followup_3_sent_at": self.now - timedelta(days=followup_3_days) if followup_3_days else None,
                },
            )

    def _upsert_user(
        self,
        *,
        username: str,
        email: str,
        first_name: str,
        last_name: str,
        phone: str,
        roles: list,
        is_staff: bool = False,
        is_superuser: bool = False,
        marketing: bool = False,
        is_dealer: bool = False,
        dealer_tier: str = DealerTier.NONE,
    ):
        User = get_user_model()
        user, _ = User.objects.get_or_create(username=username)
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.is_active = True
        user.is_staff = is_staff or is_superuser or any(role.name in {"Admin", "Master"} for role in roles)
        user.is_superuser = is_superuser
        user.set_password(self.shared_password)
        user.save()

        profile, _ = UserProfile.objects.get_or_create(user=user, defaults={"phone": phone})
        profile.phone = phone
        profile.birth_date = date(1990, 1, min(28, (len(username) % 27) + 1))
        profile.address = "123 Demo Street\nEdmonton, AB"
        profile.email_marketing_consent = marketing
        profile.email_marketing_consented_at = self.now - timedelta(days=30) if marketing else None
        profile.email_product_updates = marketing
        profile.email_service_updates = marketing
        profile.how_heard = "google" if marketing else "instagram"
        profile.email_verified_at = self.now - timedelta(days=45)
        profile.is_dealer = is_dealer
        profile.dealer_tier = dealer_tier
        profile.dealer_since = self.now - timedelta(days=120) if is_dealer else None
        profile.save()

        for role in roles:
            assign_role(user, role)
        return user

    def _upsert_service(
        self,
        name: str,
        *,
        category: ServiceCategory,
        base_price: Decimal,
        duration: int,
        description: str,
        prepayment: PrepaymentOption | None = None,
        contact_for_estimate: bool = False,
        estimate_from_price: Decimal | None = None,
    ) -> Service:
        service, _ = Service.objects.update_or_create(
            name=name,
            defaults={
                "category": category,
                "prepayment_option": prepayment,
                "base_price": base_price,
                "duration_min": duration,
                "extra_time_min": 15 if duration >= 90 else 0,
                "description": description,
                "contact_for_estimate": contact_for_estimate,
                "estimate_from_price": estimate_from_price,
            },
        )
        if not service.image:
            service.image.save(f"{slugify(name)}.png", self._image_file(), save=True)
        return service

    def _upsert_product(
        self,
        *,
        sku: str,
        name: str,
        category: Category,
        merch_category: MerchCategory | None,
        price: Decimal,
        inventory: int,
        description: str,
        import_batch: ImportBatch | None = None,
        compatible_models: list | None = None,
        is_in_house: bool = False,
        contact_for_estimate: bool = False,
        estimate_from_price: Decimal | None = None,
    ) -> Product:
        product, _ = Product.objects.update_or_create(
            sku=sku,
            defaults={
                "name": name,
                "category": category,
                "merch_category": merch_category,
                "price": price,
                "unit_cost": price * Decimal("0.62") if price else None,
                "is_in_house": is_in_house,
                "inventory": inventory,
                "currency": "CAD",
                "is_active": True,
                "import_batch": import_batch,
                "short_description": description[:200],
                "description": description,
                "compatibility": "Seeded fitment notes for admin QA.",
                "contact_for_estimate": contact_for_estimate,
                "estimate_from_price": estimate_from_price,
                "option_column_1_label": "Primary",
                "option_column_2_label": "Secondary",
            },
        )
        if compatible_models:
            product.compatible_models.set(compatible_models)
        return product

    def _upsert_background_asset(self, title: str, caption: str) -> BackgroundAsset:
        asset, _ = BackgroundAsset.objects.get_or_create(
            title=title,
            defaults={"alt_text": title, "caption": caption, "is_active": True},
        )
        if not asset.image:
            asset.image.save(f"{slugify(title)}.png", self._image_file(), save=True)
        return asset

    def _upsert_page_draft(self, instance, payload: dict) -> None:
        draft = PageCopyDraft.for_instance(instance)
        draft.data = payload
        draft.save(update_fields=["data", "updated_at"])

    def _upsert_page_section(self, instance, order: int, section_type: str, asset: BackgroundAsset, config: dict) -> None:
        content_type = ContentType.objects.get_for_model(instance.__class__)
        PageSection.objects.update_or_create(
            content_type=content_type,
            object_id=instance.pk,
            order=order,
            defaults={
                "section_type": section_type,
                "config": config,
                "background_image": asset,
                "background_color": "#111111",
                "overlay_color": "rgba(0,0,0,0.35)",
            },
        )

    def _clear_demo_page_overrides(self, instance) -> None:
        content_type = ContentType.objects.get_for_model(instance.__class__)
        PageSection.objects.filter(
            content_type=content_type,
            object_id=instance.pk,
            config__demo_seed=True,
        ).delete()

        for draft in PageCopyDraft.objects.filter(content_type=content_type, object_id=instance.pk):
            payload = draft.data or {}
            joined = " ".join(str(value) for value in payload.values())
            if "Demo " in joined or "Draft-only lead" in joined:
                draft.delete()

    def _get_solo(self, model):
        getter = getattr(model, "get_solo", None)
        if callable(getter):
            return getter()
        return model.objects.get_or_create(singleton_id=1)[0]

    def _image_file(self) -> ContentFile:
        return ContentFile(TINY_PNG)

    def _aware(self, target_date: date, hour: int, minute: int = 0):
        naive = datetime.combine(target_date, time(hour, minute))
        return timezone.make_aware(naive, timezone.get_current_timezone())

    def _next_weekday(self, start: date, weekday: int) -> date:
        days_ahead = (weekday - start.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return start + timedelta(days=days_ahead)
