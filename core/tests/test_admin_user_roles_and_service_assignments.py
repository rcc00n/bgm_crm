from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.forms import CustomUserChangeForm, ServiceMasterAdminForm
from core.models import Role, Service, ServiceMaster, UserProfile, UserRole


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
