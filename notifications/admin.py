from django.contrib import admin, messages
from django.utils import timezone

from . import services
from .models import TelegramBotSettings, TelegramMessageLog, TelegramReminder


@admin.register(TelegramBotSettings)
class TelegramBotSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "enabled",
        "notify_on_new_appointment",
        "notify_on_new_order",
        "digest_enabled",
        "updated_at",
    )
    readonly_fields = ("created_at", "updated_at", "last_digest_sent_on")
    fieldsets = (
        ("Bot identity", {"fields": ("name", "bot_token", "enabled")}),
        ("Recipients", {"fields": ("admin_chat_ids", "allowed_user_ids")}),
        ("Automation", {"fields": ("notify_on_new_appointment", "notify_on_new_order")}),
        ("Daily digest", {"fields": ("digest_enabled", "digest_hour_local", "last_digest_sent_on")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        if TelegramBotSettings.objects.exists():
            return False
        return super().has_add_permission(request)


@admin.register(TelegramMessageLog)
class TelegramMessageLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event_type", "chat_id", "success")
    list_filter = ("event_type", "success")
    search_fields = ("payload", "chat_id")
    readonly_fields = ("event_type", "chat_id", "payload", "success", "error_message", "created_at")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False


@admin.register(TelegramReminder)
class TelegramReminderAdmin(admin.ModelAdmin):
    list_display = ("title", "scheduled_for", "status", "sent_at")
    list_filter = ("status",)
    search_fields = ("title", "message")
    actions = ["send_selected_now"]
    readonly_fields = ("sent_at", "last_error", "created_at", "updated_at")
    fieldsets = (
        ("Reminder", {"fields": ("title", "message", "scheduled_for", "target_chat_ids")}),
        ("Status", {"fields": ("status", "sent_at", "last_error")}),
        ("Meta", {"fields": ("created_at", "updated_at")}),
    )

    @admin.action(description="Send selected reminders now")
    def send_selected_now(self, request, queryset):
        pending = queryset.filter(status=TelegramReminder.Status.PENDING)
        if not pending.exists():
            self.message_user(request, "Only pending reminders can be sent.", level=messages.WARNING)
            return
        sent = 0
        for reminder in pending:
            reminder.scheduled_for = timezone.now()
            reminder.save(update_fields=["scheduled_for", "updated_at"])
            services.deliver_reminder(reminder)
            sent += 1
        self.message_user(request, f"Triggered {sent} reminder(s).")
