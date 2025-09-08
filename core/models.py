from decimal import Decimal

from django.db import models
from django.contrib.auth.models import User
import uuid
from django.core.exceptions import ValidationError
from datetime import timedelta, time
import os
from django.utils import timezone
from django.utils.timezone import localtime
from core.validators import clean_phone
from django.conf import settings
from django.db.models import Sum

from storages.backends.s3boto3 import S3Boto3Storage
# --- 1. ROLES ---
from django.core.files.storage import FileSystemStorage
from django.conf import settings

from storages.backends.s3boto3 import S3Boto3Storage

def _s3_configured() -> bool:
    required = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_STORAGE_BUCKET_NAME",
        "AWS_S3_REGION_NAME",
    ]
    return all(bool(getattr(settings, key, None)) for key in required)

# не инициализируем S3, если он не настроен, чтобы не получать ValueError
try:
    MASTER_PHOTO_STORAGE = S3Boto3Storage() if _s3_configured() else FileSystemStorage()
except Exception:
    MASTER_PHOTO_STORAGE = FileSystemStorage()
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

class ClientSource(models.Model):
    source = models.CharField()

    def __str__(self):
        return f"{self.source}%"

class HowHeard(models.TextChoices):
    GOOGLE = "google", "Google search"
    INSTAGRAM = "instagram", "Instagram"
    TIKTOK = "tiktok", "TikTok"
    FRIEND = "friend", "Friends/Family"
    OTHER = "other", "Other"

# ── NEW/UPDATED: Dealer tiers, application, fields на профиле ─────────────────
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.validators import MinLengthValidator

# Если у вас уже есть UserProfile — дополним его, иначе создайте.
class DealerTier(models.TextChoices):
    NONE = "NONE", "None"
    TIER_5 = "TIER_5", "Dealer 5% (≥ $1,000)"
    TIER_10 = "TIER_10", "Dealer 10% (≥ $5,000)"
    TIER_15 = "TIER_15", "Dealer 15% (≥ $20,000)"

DEALER_THRESHOLDS = {
    DealerTier.TIER_5: 1000,
    DealerTier.TIER_10: 5000,
    DealerTier.TIER_15: 20000,
}
DEALER_DISCOUNTS = {
    DealerTier.TIER_5: 5,
    DealerTier.TIER_10: 10,
    DealerTier.TIER_15: 15,
}

class DealerApplication(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dealer_application",
        verbose_name="User",
    )
    business_name = models.CharField("Business name", max_length=128)
    website = models.URLField("Website", blank=True)
    phone = models.CharField("Phone", max_length=32, validators=[MinLengthValidator(5)])
    notes = models.TextField("Notes", blank=True)
    status = models.CharField(
        "Status", max_length=16, choices=Status.choices, default=Status.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="dealer_reviews",
        verbose_name="Reviewed by",
    )

    class Meta:
        verbose_name = "Dealer Application"
        verbose_name_plural = "Dealer Applications"
        ordering = ["-created_at"]

    def approve(self, admin_user):
        self.status = self.Status.APPROVED
        self.reviewed_at = timezone.now()
        self.reviewed_by = admin_user
        self.save(update_fields=["status", "reviewed_at", "reviewed_by"])
        # Обновим профиль пользователя
        up = getattr(self.user, "userprofile", None)
        if up:
            up.is_dealer = True
            # tier будет выставляться на основании total_spent (см. метод ниже)
            up.recompute_dealer_tier()
            up.dealer_since = up.dealer_since or timezone.now()
            up.save(update_fields=["is_dealer", "dealer_tier", "dealer_since"])

    def reject(self, admin_user):
        self.status = self.Status.REJECTED
        self.reviewed_at = timezone.now()
        self.reviewed_by = admin_user
        self.save(update_fields=["status", "reviewed_at", "reviewed_by"])



class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="userprofile")

    phone = models.CharField(max_length=32, unique=True)
    birth_date = models.DateField(null=True, blank=True)
    is_dealer = models.BooleanField("Is dealer", default=False)
    dealer_tier = models.CharField(
        "Dealer tier",
        max_length=16,
        choices=DealerTier.choices,
        default=DealerTier.NONE,
    )
    dealer_since = models.DateTimeField("Dealer since", null=True, blank=True)

    # === NEW ===
    address = models.TextField(blank=True)                         # одна строка/много строк — на твой вкус
    email_marketing_consent = models.BooleanField(default=False)   # согласие на рассылки
    email_marketing_consented_at = models.DateTimeField(null=True, blank=True)
    how_heard = models.CharField(max_length=32, choices=HowHeard.choices, blank=True)

    def set_marketing_consent(self, value: bool):
        """Удобный метод: при выставлении True заполнит timestamp, при снятии — очистит."""
        if value and not self.email_marketing_consent:
            self.email_marketing_consent = True
            self.email_marketing_consented_at = timezone.now()
        elif not value and self.email_marketing_consent:
            self.email_marketing_consent = False
            self.email_marketing_consented_at = None
            
    def __str__(self):
        return f"{self.user} Profile"
    
    



   

    def total_spent_usd(self) -> float:
        """
        Total spent by the user:
        - Sum of all Payment.amount for appointments where client=self.user
        - PLUS sum of service.base_price for paid appointments that have NO payments
        (to avoid double counting).
        """
        try:
            from core.models import Payment, Appointment, PaymentStatus
        except Exception:
            return 0.0

        # 1) Sum of all payments
        payments_total = Payment.objects.filter(
            appointment__client=self.user
        ).aggregate(s=Sum("amount"))["s"] or 0

        # 2) Paid appointments that have NO payments
        paid_names = {"Paid", "Completed", "Settled", "paid", "completed", "settled"}
        paid_statuses = PaymentStatus.objects.filter(name__in=paid_names)

        appts_without_payments_total = Appointment.objects.filter(
            client=self.user,
            payment_status__in=paid_statuses,
            payment__isnull=True,  # no payments linked
        ).aggregate(s=Sum("service__base_price"))["s"] or 0

        return float(payments_total) + float(appts_without_payments_total)


    def recompute_dealer_tier(self) -> None:
        spent = self.total_spent_usd()
        new_tier = DealerTier.NONE
        if spent >= DEALER_THRESHOLDS[DealerTier.TIER_15]:
            new_tier = DealerTier.TIER_15
        elif spent >= DEALER_THRESHOLDS[DealerTier.TIER_10]:
            new_tier = DealerTier.TIER_10
        elif spent >= DEALER_THRESHOLDS[DealerTier.TIER_5]:
            new_tier = DealerTier.TIER_5
        self.dealer_tier = new_tier  # do NOT flip is_dealer here





    @property
    def dealer_discount_percent(self) -> int:
        return DEALER_DISCOUNTS.get(self.dealer_tier, 0)

# --- 2. SERVICES ---

class ServiceCategory(models.Model):
    """
    Represents a service offered in the system (e.g., haircut, massage).
    """
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class PrepaymentOption(models.Model):
    """
    Defines available prepayment percentage options.
    """
    percent = models.IntegerField()

    def __str__(self):
        return f"{self.percent}%"

# imports должны уже быть в файле:
# import uuid
# from decimal import Decimal
# from django.utils import timezone
# from django.db import models
# (и ваши ServiceCategory, PrepaymentOption)

class Service(models.Model):
    """
    Represents a service offered in the system (e.g., haircut, massage).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    category = models.ForeignKey(ServiceCategory, on_delete=models.CASCADE, blank=True, null=True)
    prepayment_option = models.ForeignKey(PrepaymentOption, on_delete=models.CASCADE, blank=True, null=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_min = models.IntegerField()
    extra_time_min = models.IntegerField(null=True, blank=True)

    # NEW: cover image for service card
    image = models.ImageField(
        "Image",
        upload_to="services/",
        blank=True,
        null=True,
        help_text="Upload a service cover image (recommended ratio ~16:9).",
    )

    def __str__(self):
        return self.name

    # Admin inline preview (safe to call in admin)
    def image_preview(self):
        from django.utils.html import format_html
        if getattr(self, "image", None):
            try:
                return format_html('<img src="{}" style="height:60px;border-radius:8px">', self.image.url)
            except Exception:
                return "—"
        return "—"
    image_preview.short_description = "Preview"

    def get_active_discount(self):
        today = timezone.now().date()
        return self.discounts.filter(start_date__lte=today, end_date__gte=today).first()

    def get_discounted_price(self):
        """
        Call instead of price to get discounted price or base_price if discount is not set
        """
        discount = self.get_active_discount()
        if discount:
            discount_multiplier = Decimal(1) - (Decimal(discount.discount_percent) / Decimal(100))
            return (self.base_price * discount_multiplier).quantize(Decimal('0.01'))
        return self.base_price


class MasterRoom(models.Model):
    """
    Rooms where Master will operate
    """
    room = models.CharField(max_length=20)

    def __str__(self):
        return self.room

class MasterProfile(models.Model):
    """
    Дополнительная информация о мастере: профессия, график работы, цвет и т.д.
    """
    user = models.OneToOneField(CustomUserDisplay, on_delete=models.CASCADE, related_name="master_profile")
    profession = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    room = models.ForeignKey(MasterRoom, on_delete=models.CASCADE, blank=True, null=True)
    work_start = models.TimeField(default="08:00")
    work_end = models.TimeField(default="21:00")
    photo = models.ImageField(upload_to="masters/", storage=MASTER_PHOTO_STORAGE, blank=True, null=True)


    def __str__(self):
        return f"{self.user.get_full_name()}"

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

        formatted = localtime(self.start_time).strftime("%Y-%m-%d %H:%M")
        return f"{self.client} for {self.service} at {formatted}"

    def clean(self):
        if self.start_time and self.start_time.time() > time(23, 59):
            raise ValidationError({
                "start_time": "Время начала не может быть позже 23:59."
            })

        # Остальная логика…
        if not self.master or not self.service or not self.start_time:
            return

        cancelled_status = AppointmentStatus.objects.filter(name="Cancelled").first()
        # Проверка на пересечение с другими записями
        overlapping = Appointment.objects.filter(
            master=self.master,
            start_time__lt=self.start_time + timedelta(minutes=self.service.duration_min),
            start_time__gte=self.start_time - timedelta(hours=3)
        ).exclude(id=self.id)

        overlapping = overlapping.exclude(
            appointmentstatushistory__status=cancelled_status
        )

        this_end = self.start_time + timedelta(minutes=self.service.duration_min)
        for appt in overlapping:
            other_end = appt.start_time + timedelta(minutes=appt.service.duration_min)
            if self.start_time < other_end and this_end > appt.start_time:
                raise ValidationError({
                    "start_time": "This appointment overlaps with another appointment for the same master."
                })

            # --- 🔒 Проверка пересечения по комнате ---
        master_profile = getattr(self.master, "master_profile", None)
        if master_profile and master_profile.room:
            overlapping_room = Appointment.objects.filter(
                master__master_profile__room=master_profile.room,
                start_time__lt=this_end,
                start_time__gte=self.start_time - timedelta(hours=3)
            ).exclude(id=self.id)

            for appt in overlapping_room:
                appt_end = appt.start_time + timedelta(minutes=appt.service.duration_min)
                if self.start_time < appt_end and this_end > appt.start_time:
                    raise ValidationError({
                        "start_time": f"Room '{master_profile.room}' is occupied at this time."
                    })
        # Проверка на отпуск / отгулы
        unavailable_periods = MasterAvailability.objects.filter(master=self.master)

        for period in unavailable_periods:
            if self.start_time < period.end_time and this_end > period.start_time:
                raise ValidationError({"start_time": "This appointment falls within the master's time off or vacation."})

        master_profile = getattr(self.master, "master_profile", None)
        if master_profile and self.start_time:
            local_start_dt = localtime(self.start_time)

            # длительность услуги с учётом extra_time_min
            extra_min = self.service.extra_time_min or 0
            total_minutes = self.service.duration_min + extra_min
            local_end_dt = local_start_dt + timedelta(minutes=total_minutes)

            # рабочее окно мастера на ДАННУЮ дату
            ws: time = master_profile.work_start
            we: time = master_profile.work_end

            work_start_dt = local_start_dt.replace(hour=ws.hour, minute=ws.minute, second=0, microsecond=0)
            work_end_dt   = local_start_dt.replace(hour=we.hour, minute=we.minute, second=0, microsecond=0)

            # Если смена «через полночь» (например, 22:00–06:00), расширяем конец на следующий день
            if work_end_dt <= work_start_dt:
                work_end_dt += timedelta(days=1)
                # если встреча начинается после полуночи (т.е. до work_end), тоже считаем её «следующим днём»
                if local_end_dt <= work_start_dt:
                    local_end_dt += timedelta(days=1)
                if local_start_dt <= work_start_dt:
                    local_start_dt += timedelta(days=1)

            # 1) старт раньше начала смены
            if local_start_dt < work_start_dt:
                raise ValidationError({
                    "start_time": f"Start time ({local_start_dt.strftime('%H:%M')}) earlier than masters shift starts git st "
                                  f"({work_start_dt.strftime('%H:%M')})."
                })

            # 2) конец позже конца смены
            if local_end_dt > work_end_dt:
                raise ValidationError({
                    "start_time": f"The appointment ends at ({local_end_dt.strftime('%H:%M')}) which is later then master's end of shift "
                                  f"({work_end_dt.strftime('%H:%M')})."
                })

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
    USER = 'user'
    ADMIN = 'admin'

    OWNER_CHOICES = [
        (USER, 'User'),
        (ADMIN, 'Admin'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUserDisplay, on_delete=models.CASCADE)
    file = models.FileField(upload_to='client_files/', storage=S3Boto3Storage()) # stored in S3!
    file_type = models.CharField(max_length=50, editable=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.CharField(
        max_length=10,
        choices=OWNER_CHOICES,
        default=USER,
        help_text="Who uploaded the file: admin or user"
    )

    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional description (e.g., 'Form before procedure')"
    )
    def save(self, *args, **kwargs):
        if self.file and not self.file_type:
            name, extension = os.path.splitext(self.file.name)
            self.file_type = extension.lower().lstrip('.')  # без точки
        super().save(*args, **kwargs)

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

    def clean(self):
        super().clean()

        if not self.master or not self.start_time or not self.end_time:
            return  # Не валидируем, если что-то не заполнено

        # Найдём все записи мастера, которые пересекаются с отпуском
        overlapping_appointments = Appointment.objects.filter(
            master=self.master,
            start_time__lt=self.end_time,
            start_time__gte=self.start_time - timedelta(hours=3)  # захватываем буфер
        )

        for appt in overlapping_appointments:
            appt_end = appt.start_time + timedelta(minutes=appt.service.duration_min)
            if self.start_time < appt_end and self.end_time > appt.start_time:
                raise ValidationError({
                    "start_time": "Vacation overlaps with existing appointments",
                })


class ClientReview(models.Model):
    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.CASCADE,
        related_name='review',
        help_text="One review per one appointment"
    )
    rating = models.PositiveSmallIntegerField(
        choices=[(i, f"{i} ★") for i in range(1, 6)],
        help_text="Rating 1 to 5"
    )
    comment = models.TextField(blank=True, help_text="Not obligatory text comment")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Review {self.rating}★ for {self.appointment}"

    class Meta:
        verbose_name = "Client Review"
        verbose_name_plural = "Client Reviews"


class ServiceDiscount(models.Model):
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='discounts')
    discount_percent = models.PositiveIntegerField(help_text="Percent of discount")
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        verbose_name = "Service Discount"
        verbose_name_plural = "Service Discounts"
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.discount_percent}% off on {self.service.name} ({self.start_date} – {self.end_date})"

    def is_active(self):
        today = timezone.now().date()
        return self.start_date <= today <= self.end_date


class PromoCode(models.Model):
    code = models.CharField(max_length=20, unique=True)
    discount_percent = models.PositiveIntegerField(help_text="discount in percents(0-100)")
    active = models.BooleanField(default=True)
    start_date = models.DateField()
    end_date = models.DateField()
    applicable_services = models.ManyToManyField(Service, blank=True, help_text="leave empty to apply to all services")

    def is_valid_for(self, service, today=None):
        today = today or timezone.now().date()
        return (
                self.active and
                self.start_date <= today <= self.end_date and
                (self.applicable_services.count() == 0 or self.applicable_services.filter(pk=service.pk).exists())
        )

    def __str__(self):
        return self.code

class AppointmentPromoCode(models.Model):
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE)
    promocode = models.ForeignKey(PromoCode, on_delete=models.CASCADE)

    def clean(self):
        if self.promocode.end_date < timezone.now().date():
            raise ValidationError({
                "promocode": "This promocode is expired."
            })
        now = timezone.now()
        discounts = ServiceDiscount.objects.filter(
            service=self.appointment.service,
            start_date__lte=now,
            end_date__gte=now
        ).exists()
        if discounts:
            raise ValidationError({
                "promocode": "This Service already has a discount. Promocode can't be applied"
            })

# app: core/models.py
from django.db import models

class SiteSettings(models.Model):
    hero_preview = models.ImageField(upload_to='hero/', blank=True, null=True)
    hero_alt = models.CharField(max_length=140, blank=True, default='Project preview')

    class Meta:
        verbose_name = "Site settings"
        verbose_name_plural = "Site settings"

    def __str__(self):
        return "Site settings"
