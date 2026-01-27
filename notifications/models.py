import re
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


def _parse_id_list(raw: str) -> list[int]:
    """
    Converts a comma/space separated string into a list of Telegram chat/user IDs.
    """
    if not raw:
        return []
    ids: list[int] = []
    for chunk in re.split(r"[\\s,]+", raw.strip()):
        if not chunk:
            continue
        try:
            ids.append(int(chunk))
        except ValueError:
            continue
    return ids


class TelegramBotSettings(models.Model):
    """
    Singleton-like holder for Telegram bot credentials and behavior toggles.
    """

    name = models.CharField(max_length=120, default="Operations bot")
    bot_token = models.CharField(
        max_length=255,
        blank=True,
        help_text="Bot token issued by BotFather."
    )
    enabled = models.BooleanField(
        default=False,
        help_text="Disable to temporarily stop sending Telegram notifications.",
    )
    admin_chat_ids = models.TextField(
        blank=True,
        help_text="Comma or space separated chat IDs that should receive automated alerts.",
    )
    allowed_user_ids = models.TextField(
        blank=True,
        help_text="Optional Telegram user IDs allowed to interact with the bot commands. "
                  "Fallbacks to admin chats when empty.",
    )
    notify_on_new_appointment = models.BooleanField(default=True)
    notify_on_new_order = models.BooleanField(default=True)
    digest_enabled = models.BooleanField(
        default=False,
        help_text="Enable to send a consolidated daily summary through the bot.",
    )
    digest_hour_local = models.PositiveSmallIntegerField(
        default=8,
        validators=[MinValueValidator(0), MaxValueValidator(23)],
        help_text="Hour (0-23) at which the digest command should run (local server time).",
    )
    last_digest_sent_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Telegram bot settings"
        verbose_name_plural = "Telegram bot settings"

    def __str__(self) -> str:
        return self.name

    def clean(self):
        if TelegramBotSettings.objects.exclude(pk=self.pk).exists():
            raise ValidationError("Only one Telegram bot configuration is allowed.")

    @property
    def slot_chat_ids(self) -> list[int]:
        if not self.pk:
            return []
        return list(self.recipient_slots.values_list("chat_id", flat=True))

    @property
    def chat_id_list(self) -> list[int]:
        """
        Returns configured recipients from structured slots first,
        then falls back to free-form IDs (keeps legacy behavior).
        """
        slot_ids = self.slot_chat_ids
        legacy_ids = [cid for cid in _parse_id_list(self.admin_chat_ids) if cid not in slot_ids]
        return slot_ids + legacy_ids

    @property
    def allowed_user_id_list(self) -> list[int]:
        ids = _parse_id_list(self.allowed_user_ids)
        return ids or self.chat_id_list

    @property
    def is_ready(self) -> bool:
        return bool(self.enabled and self.bot_token and self.chat_id_list)

    @classmethod
    def load(cls) -> "TelegramBotSettings | None":
        return cls.objects.first()

    @classmethod
    def load_active(cls) -> "TelegramBotSettings | None":
        obj = cls.load()
        if obj and obj.is_ready:
            return obj
        return None


class TelegramRecipientSlot(models.Model):
    """
    Discrete slots for Telegram recipients (easier than a raw text field).
    """

    settings = models.ForeignKey(
        TelegramBotSettings,
        related_name="recipient_slots",
        on_delete=models.CASCADE,
    )
    chat_id = models.BigIntegerField(unique=True)
    label = models.CharField(
        max_length=120,
        blank=True,
        help_text="Optional hint about who owns this chat ID.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["chat_id"]
        verbose_name = "Telegram recipient slot"
        verbose_name_plural = "Telegram recipient slots"

    def __str__(self) -> str:
        suffix = f" — {self.label}" if self.label else ""
        return f"{self.chat_id}{suffix}"


class TelegramMessageLog(models.Model):
    """
    Persists each outbound message for auditing and troubleshooting.
    """

    EVENT_APPOINTMENT_CREATED = "appointment_created"
    EVENT_ORDER_CREATED = "order_created"
    EVENT_SERVICE_LEAD = "service_lead"
    EVENT_FITMENT_REQUEST = "fitment_request"
    EVENT_SITE_NOTICE_WELCOME = "site_notice_welcome"
    EVENT_ORDER_REVIEW_REQUEST = "order_review_request"
    EVENT_REMINDER = "reminder"
    EVENT_DIGEST = "digest"
    EVENT_MANUAL = "manual"

    event_type = models.CharField(max_length=64, db_index=True)
    chat_id = models.BigIntegerField()
    payload = models.TextField()
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Telegram message log"
        verbose_name_plural = "Telegram message log"

    def __str__(self) -> str:
        state = "sent" if self.success else "failed"
        return f"{self.event_type} → {self.chat_id} ({state})"


class TelegramContact(models.Model):
    """
    Address book for reusable Telegram recipients.
    """

    name = models.CharField(max_length=160)
    chat_id = models.BigIntegerField(unique=True)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Telegram contact"
        verbose_name_plural = "Telegram contacts"

    def __str__(self) -> str:
        return f"{self.name} ({self.chat_id})"


class TelegramReminder(models.Model):
    """
    Allows staff to schedule ad-hoc reminders that the bot will deliver later.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    title = models.CharField(max_length=160)
    message = models.TextField()
    scheduled_for = models.DateTimeField(default=timezone.now)
    target_chat_ids = models.TextField(
        blank=True,
        help_text="Optional override for chat IDs. Uses admin recipients when empty.",
    )
    contacts = models.ManyToManyField(
        TelegramContact,
        blank=True,
        related_name="reminders",
        help_text="Select saved contacts to receive this reminder.",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-scheduled_for"]
        verbose_name = "Telegram reminder"
        verbose_name_plural = "Telegram reminders"

    def __str__(self) -> str:
        return self.title

    @property
    def chat_id_list(self) -> list[int]:
        manual_ids = _parse_id_list(self.target_chat_ids)
        contact_ids: list[int] = []
        if self.pk:
            contact_ids = list(self.contacts.values_list("chat_id", flat=True))
        combined = contact_ids + [cid for cid in manual_ids if cid not in contact_ids]
        return combined

    def mark_sent(self, *, success: bool, error_message: str | None = None):
        self.status = self.Status.SENT if success else self.Status.FAILED
        self.sent_at = timezone.now()
        self.last_error = error_message or ""
        self.save(update_fields=["status", "sent_at", "last_error", "updated_at"])

    def clean(self):
        if self.status == self.Status.PENDING and self.scheduled_for < timezone.now() - timedelta(days=30):
            raise ValidationError({"scheduled_for": "Please choose a future date for pending reminders."})

    @classmethod
    def due(cls):
        return cls.objects.filter(
            status=cls.Status.PENDING,
            scheduled_for__lte=timezone.now(),
        )
