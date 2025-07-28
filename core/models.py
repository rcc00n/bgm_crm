from django.db import models
from django.contrib.auth.models import User
import uuid
from django.core.exceptions import ValidationError
from datetime import timedelta, datetime
from storages.backends.s3boto3 import S3Boto3Storage
# --- 1. ROLES ---

class Role(models.Model):
    """
    Represents a role that can be assigned to a user (e.g., Master, Client, Admin).
    """
    name = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return self.name


class CustomUserDisplay(User):
    """
    Proxy model for Django's User to allow customization in admin views and display logic.
    """
    class Meta:
        proxy = True

    def __str__(self):
        full_name = self.get_full_name()
        return full_name if full_name else self.username


class UserRole(models.Model):
    """
    Links a user to a specific role with a timestamp of when the role was assigned.
    """
    user = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'role')

    def __str__(self):
        return f"{self.user} → {self.role.name}"

from core.validators import clean_phone
class UserProfile(models.Model):
    """
    Additional user information extending the Django User model.
    """
    user = models.OneToOneField(CustomUserDisplay, on_delete=models.CASCADE)
    phone = models.CharField(max_length=20, unique=True, blank=False,  validators=[clean_phone] )
    birth_date = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=25, default="In-store")
    
    def __str__(self):
        return f"{self.user} Profile"

# --- 2. SERVICES ---

class ServiceCategory(models.Model):
    """
    Represents a service offered in the system (e.g., haircut, massage).
    """
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name



class Service(models.Model):
    """
    Represents a service offered in the system (e.g., haircut, massage).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    category = models.ForeignKey(ServiceCategory, on_delete=models.CASCADE, blank=True, null=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_min = models.IntegerField()
    extra_time_min = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return self.name



class ServiceMaster(models.Model):
    """
    Connects a specific service with a master who can perform it.
    """
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    master = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.master} → {self.service.name}"

# --- 3. APPOINTMENTS ---

class AppointmentStatus(models.Model):
    """
    Statuses an appointment can have (e.g., Confirmed, Cancelled).
    """
    name = models.CharField(max_length=20)

    def __str__(self):
        return self.name


class PaymentStatus(models.Model):
    """
    Describes the status of a payment (e.g., Paid, Pending).
    """
    name = models.CharField(max_length=20)

    def __str__(self):
        return self.name


class Appointment(models.Model):
    """
    Represents a scheduled appointment between a client and a master for a service.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE, related_name='appointments_as_client')
    master = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE, related_name='appointments_as_master')
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    start_time = models.DateTimeField()
    payment_status = models.ForeignKey(PaymentStatus, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        dt = datetime.fromisoformat(str(self.start_time))  # автоматически распознаёт +00:00
        formatted = dt.strftime("%Y-%m-%d %H:%M")
        return f"{self.client} for {self.service} at {formatted}"

    def clean(self):
        # Проверка на пересечение с другими записями
        overlapping = Appointment.objects.filter(
            master=self.master,
            start_time__lt=self.start_time + timedelta(minutes=self.service.duration_min),
            start_time__gte=self.start_time - timedelta(hours=3)
        ).exclude(id=self.id)

        this_end = self.start_time + timedelta(minutes=self.service.duration_min)
        for appt in overlapping:
            other_end = appt.start_time + timedelta(minutes=appt.service.duration_min)
            if self.start_time < other_end and this_end > appt.start_time:
                raise ValidationError({
                    "start_time": "This appointment overlaps with another appointment for the same master."
                })


        # Проверка на отпуск / отгулы
        unavailable_periods = MasterAvailability.objects.filter(master=self.master)

        for period in unavailable_periods:
            if self.start_time < period.end_time and this_end > period.start_time:
                raise ValidationError({"start_time": "This appointment falls within the master's time off or vacation."})



class AppointmentStatusHistory(models.Model):
    """
    Tracks status changes for appointments, including who made the change and when.
    """
    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE)
    status = models.ForeignKey(AppointmentStatus, on_delete=models.CASCADE)
    set_by = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)
    set_at = models.DateTimeField(auto_now_add=True)

# --- 4. PAYMENTS ---

class PaymentMethod(models.Model):
    """
    Represents a method of payment (e.g., Credit Card, Cash).
    """
    name = models.CharField(max_length=20)

    def __str__(self):
        return self.name


class Payment(models.Model):
    """
    Stores payment records for appointments.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.ForeignKey(PaymentMethod, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

# --- 5. PREPAYMENTS ---

class PrepaymentOption(models.Model):
    """
    Defines available prepayment percentage options.
    """
    percent = models.IntegerField()

    def __str__(self):
        return f"{self.percent}%"


class AppointmentPrepayment(models.Model):
    """
    Links a prepayment option to a specific appointment.
    """
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE)
    option = models.ForeignKey(PrepaymentOption, on_delete=models.CASCADE)

# --- 6. FILES ---

class ClientFile(models.Model):
    """
    Represents a file uploaded for a user, such as a document or image.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)
    file = models.FileField(upload_to='client_files/', storage=S3Boto3Storage()) # stored in S3!
    file_type = models.CharField(max_length=50)
    uploaded_at = models.DateTimeField(auto_now_add=True)

# --- 7. NOTIFICATIONS ---

class Notification(models.Model):
    """
    Represents a notification sent to a user regarding an appointment.
    Supports email and SMS channels.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)
    appointment = models.ForeignKey(Appointment, on_delete=models.SET_NULL, null=True, blank=True)
    channel = models.CharField(max_length=10, choices=[('email', 'Email'), ('sms', 'SMS')])
    message = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        """
        Triggers message sending based on the selected channel (email or SMS).
        """
        is_new = self._state.adding
        super().save(*args, **kwargs)

        if is_new:
            if self.channel == 'email':
                self.send_email()
            elif self.channel == 'sms':
                self.send_sms()

    def send_email(self):
        """
        Stub: logic to send an email message to the user.
        """
        print(f"[EMAIL] To {self.user}: {self.message}")

    def send_sms(self):
        """
        Stub: logic to send an SMS message to the user.
        """
        print(f"[SMS] To {self.user}: {self.message}")

# --- 8. MASTERS ---
class MasterProfile(models.Model):
    """
    Дополнительная информация о мастере: профессия, график работы, цвет и т.д.
    """
    user = models.OneToOneField(CustomUserDisplay, on_delete=models.CASCADE, related_name="master_profile")
    profession = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    work_start = models.TimeField(default="08:00")
    work_end = models.TimeField(default="21:00")

    def __str__(self):
        return f"Master: {self.user.get_full_name()}"

class MasterAvailability(models.Model):
    VACATION = 'vacation'
    LUNCH = 'lunch'
    BREAK = 'break'

    REASON_CHOICES = [
        (VACATION, 'Vacation'),
        (LUNCH, 'Lunch'),
        (BREAK, 'Break'),
    ]

    master = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    reason = models.CharField(
        max_length=20,
        choices=REASON_CHOICES,
        default=VACATION,
        help_text="Reason for time off"
    )

    class Meta:
        verbose_name = "Time Off / Vacation"
        verbose_name_plural = "Time Offs / Vacations"

    def __str__(self):
        return f"{self.master} → {self.get_reason_display()} from {self.start_time} to {self.end_time}"
