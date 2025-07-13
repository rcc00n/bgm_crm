from django.db import models
from django.contrib.auth.models import User
import uuid

# --- 1. ROLES ---

class Role(models.Model):
    name = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return self.name

class CustomUserDisplay(User):
    class Meta:
        proxy = True

    def __str__(self):
        full_name = self.get_full_name()
        return full_name if full_name else self.username

class UserRole(models.Model):
    user = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'role')

    def __str__(self):
        return f"{self.user} → {self.role.name}"



class UserProfile(models.Model):
    user = models.OneToOneField(CustomUserDisplay, on_delete=models.CASCADE)
    phone = models.CharField(max_length=20, unique=True)
    birth_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.user} Profile"

# --- 2. SERVICES ---

class Service(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_min = models.IntegerField()
    extra_time_min = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return self.name


class ServiceMaster(models.Model):
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    master = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.master} → {self.service.name}"


# --- 3. APPOINTMENTS ---

class AppointmentStatus(models.Model):
    name = models.CharField(max_length=20)

    def __str__(self):
        return self.name

class PaymentStatus(models.Model):
    name = models.CharField(max_length=20)

    def __str__(self):
        return self.name


class Appointment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE, related_name='appointments_as_client')
    master = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE, related_name='appointments_as_master')
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    start_time = models.DateTimeField()
    payment_status = models.ForeignKey(PaymentStatus, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.client} for {self.service} "


class AppointmentStatusHistory(models.Model):
    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE)
    status = models.ForeignKey(AppointmentStatus, on_delete=models.CASCADE)
    set_by = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)
    set_at = models.DateTimeField(auto_now_add=True)


# --- 4. PAYMENTS ---


class PaymentMethod(models.Model):
    name = models.CharField(max_length=20)

    def __str__(self):
        return self.name


class Payment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.ForeignKey(PaymentMethod, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)


# --- 5. PREPAYMENTS ---

class PrepaymentOption(models.Model):
    percent = models.IntegerField()

    def __str__(self):
        return f"{self.percent}%"


class AppointmentPrepayment(models.Model):
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE)
    option = models.ForeignKey(PrepaymentOption, on_delete=models.CASCADE)


# --- 6. FILES ---

class ClientFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)
    file_url = models.URLField()
    file_type = models.CharField(max_length=50)
    uploaded_at = models.DateTimeField(auto_now_add=True)


# --- 7. NOTIFICATIONS ---

class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)
    appointment = models.ForeignKey(Appointment, on_delete=models.SET_NULL, null=True, blank=True)
    channel = models.CharField(max_length=10, choices=[('email', 'Email'), ('sms', 'SMS')])
    message = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)


    def save(self, *args, **kwargs):
        """
        Add the actions to send the message on email or SMS here
        :param args:
        :param kwargs:
        :return:
        """
        is_new = self._state.adding
        super().save(*args, **kwargs)

        if is_new:
            if self.channel == 'email':
                self.send_email()
            elif self.channel == 'sms':
                self.send_sms()

    def send_email(self):
            print(f"[EMAIL] To {self.user}: {self.message}")

    def send_sms(self):
            print(f"[SMS] To {self.user}: {self.message}")
