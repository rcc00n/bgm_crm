from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.forms import CustomUserChangeForm, MasterCreateFullForm, ServiceAdminForm, ServiceMasterAdminForm
from core.models import (
    MasterProfile,
    PageView,
    Role,
    Service,
    ServiceMaster,
    UserProfile,
    UserRole,
    VisitorSession,
)


class AdminUserRoleFormTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.superuser = self.user_model.objects.create_superuser(
            username="admin-user-roles",
            email="admin-user-roles@example.com",
            password="StrongPass123!",
        )
        self.client_role = Role.objects.create(name="Client")
        self.admin_role = Role.objects.create(name="Admin")
        self.sales_role = Role.objects.create(name="Sales")

        self.user = self.user_model.objects.create_user(
            username="target-user",
            email="target-user@example.com",
            password="StrongPass123!",
            first_name="Target",
            last_name="User",
            is_active=True,
            is_staff=False,
        )
        UserProfile.objects.create(user=self.user, phone="+14035550101")
        UserRole.objects.create(user=self.user, role=self.client_role)

    def test_user_change_page_renders_roles_field(self):
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("admin:auth_user_change", args=[self.user.pk]), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="roles"', html=False)
        self.assertContains(response, "Assign roles directly from the user profile card.")
        self.assertNotContains(response, "Staff time tracking")

    def test_user_change_page_shows_staff_time_tracking_summary(self):
        self.client.force_login(self.superuser)
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])

        session = VisitorSession.objects.create(
            session_key="staff-tracking-session",
            user=self.user,
            user_email_snapshot=self.user.email,
            user_name_snapshot=self.user.get_full_name(),
            landing_path="/admin/",
        )
        now = timezone.now()
        PageView.objects.create(
            session=session,
            user=self.user,
            page_instance_id="staff-tracking-page-view",
            path="/admin/core/appointment/",
            full_path="/admin/core/appointment/",
            page_title="Appointments",
            started_at=now - timedelta(hours=2),
            duration_ms=2 * 60 * 60 * 1000,
        )

        response = self.client.get(reverse("admin:auth_user_change", args=[self.user.pk]), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staff time tracking")
        self.assertContains(response, "Last 7 days")
        self.assertContains(response, "02:00:00")
        self.assertContains(response, reverse("admin-staff-usage"))

    def test_user_change_form_replaces_roles_and_promotes_staff_for_admin_role(self):
        form = CustomUserChangeForm(
            data={
                "username": self.user.username,
                "email": self.user.email,
                "first_name": self.user.first_name,
                "last_name": self.user.last_name,
                "phone": self.user.userprofile.phone,
                "birth_date_month": "",
                "birth_date_day": "",
                "birth_date_year": "",
                "roles": [self.admin_role.pk, self.sales_role.pk],
                "is_active": "on",
                "password": self.user.password,
            },
            instance=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors.as_text())
        saved_user = form.save()

        self.assertTrue(saved_user.is_staff)
        self.assertEqual(
            set(saved_user.userrole_set.values_list("role__name", flat=True)),
            {"Admin", "Sales"},
        )

    def test_user_change_form_creates_master_profile_when_master_role_selected(self):
        master_role = Role.objects.create(name="Master")

        form = CustomUserChangeForm(
            data={
                "username": self.user.username,
                "email": self.user.email,
                "first_name": self.user.first_name,
                "last_name": self.user.last_name,
                "phone": self.user.userprofile.phone,
                "birth_date_month": "",
                "birth_date_day": "",
                "birth_date_year": "",
                "roles": [master_role.pk],
                "is_active": "on",
                "password": self.user.password,
            },
            instance=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors.as_text())
        saved_user = form.save()

        self.assertTrue(saved_user.is_staff)
        self.assertTrue(MasterProfile.objects.filter(user=saved_user).exists())


class MasterCreateFullFormTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.existing_user = self.user_model.objects.create_user(
            username="existing-master",
            email="existing-master@example.com",
            password="StrongPass123!",
            first_name="Existing",
            last_name="Master",
            is_active=True,
        )
        UserProfile.objects.create(user=self.existing_user, phone="+14035550111")

    def test_duplicate_username_is_reported_as_form_error(self):
        form = MasterCreateFullForm(
            data={
                "username": self.existing_user.username,
                "email": "fresh-master@example.com",
                "first_name": "Fresh",
                "last_name": "Master",
                "phone": "+14035550112",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "work_start": "08:00",
                "work_end": "17:00",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    def test_duplicate_email_is_reported_as_form_error(self):
        form = MasterCreateFullForm(
            data={
                "username": "fresh-master",
                "email": self.existing_user.email,
                "first_name": "Fresh",
                "last_name": "Master",
                "phone": "+14035550113",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "work_start": "08:00",
                "work_end": "17:00",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_save_creates_master_profile_and_assigns_master_role(self):
        Role.objects.create(name="Master")
        form = MasterCreateFullForm(
            data={
                "username": "brand-new-master",
                "email": "brand-new-master@example.com",
                "first_name": "Brand",
                "last_name": "New",
                "phone": "+14035550114",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "work_start": "08:00",
                "work_end": "17:00",
            }
        )

        self.assertTrue(form.is_valid(), form.errors.as_text())
        profile = form.save()

        self.assertTrue(MasterProfile.objects.filter(pk=profile.pk).exists())
        self.assertEqual(
            set(profile.user.userrole_set.values_list("role__name", flat=True)),
            {"Master"},
        )


class AdminServiceAssignmentsTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.superuser = self.user_model.objects.create_superuser(
            username="admin-service-assignments",
            email="admin-service-assignments@example.com",
            password="StrongPass123!",
        )
        self.master_role = Role.objects.create(name="Master")
        self.master = self.user_model.objects.create_user(
            username="service-master",
            email="service-master@example.com",
            password="StrongPass123!",
            first_name="Service",
            last_name="Master",
            is_active=True,
            is_staff=True,
        )
        UserRole.objects.create(user=self.master, role=self.master_role)
        self.second_master = self.user_model.objects.create_user(
            username="service-master-2",
            email="service-master-2@example.com",
            password="StrongPass123!",
            first_name="Backup",
            last_name="Master",
            is_active=True,
            is_staff=True,
        )
        UserRole.objects.create(user=self.second_master, role=self.master_role)

        self.service_a = Service.objects.create(
            name="Alignment",
            description="Alignment service",
            base_price=Decimal("100.00"),
            duration_min=60,
        )
        self.service_b = Service.objects.create(
            name="Dyno Tune",
            description="Dyno tune service",
            base_price=Decimal("200.00"),
            duration_min=120,
        )
        self.service_c = Service.objects.create(
            name="Inspection",
            description="Inspection service",
            base_price=Decimal("80.00"),
            duration_min=45,
        )

    def test_service_change_page_renders_staff_picker(self):
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("admin:core_service_change", args=[self.service_a.pk]), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="staff_members"', html=False)
        self.assertContains(response, "Select the staff members who can perform this service")

    def test_service_admin_form_replaces_staff_assignments_for_service(self):
        ServiceMaster.objects.create(master=self.master, service=self.service_a)

        form = ServiceAdminForm(
            data={
                "name": self.service_a.name,
                "description": self.service_a.description,
                "base_price": "100.00",
                "duration_min": "60",
                "staff_members": [self.second_master.pk],
            },
            instance=self.service_a,
        )

        self.assertTrue(form.is_valid(), form.errors.as_text())
        saved_service = form.save()

        self.assertEqual(saved_service.pk, self.service_a.pk)
        self.assertEqual(
            set(ServiceMaster.objects.filter(service=self.service_a).values_list("master__username", flat=True)),
            {"service-master-2"},
        )

    def test_service_assignments_add_page_renders_bulk_controls(self):
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("admin:core_servicemaster_add"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="assign_all_services"', html=False)
        self.assertContains(response, "Assign all current services")
        self.assertContains(response, "replaces the full assignment set for this staff member")

    def test_assign_all_services_creates_full_assignment_set(self):
        form = ServiceMasterAdminForm(
            data={
                "master": self.master.pk,
                "assign_all_services": "on",
            }
        )

        self.assertTrue(form.is_valid(), form.errors.as_text())
        form.save()

        self.assertEqual(
            set(ServiceMaster.objects.filter(master=self.master).values_list("service__name", flat=True)),
            {"Alignment", "Dyno Tune", "Inspection"},
        )

    def test_selected_services_replace_existing_assignment_set(self):
        current_assignment = ServiceMaster.objects.create(master=self.master, service=self.service_a)
        ServiceMaster.objects.create(master=self.master, service=self.service_b)

        form = ServiceMasterAdminForm(
            data={
                "master": self.master.pk,
                "services": [str(self.service_b.pk), str(self.service_c.pk)],
            },
            instance=current_assignment,
        )

        self.assertTrue(form.is_valid(), form.errors.as_text())
        saved_assignment = form.save()

        self.assertEqual(saved_assignment.pk, current_assignment.pk)
        self.assertEqual(
            set(ServiceMaster.objects.filter(master=self.master).values_list("service__name", flat=True)),
            {"Dyno Tune", "Inspection"},
        )
        self.assertEqual(ServiceMaster.objects.filter(master=self.master).count(), 2)
