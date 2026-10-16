"""Админка модуля «Уведомления»: правила, получатели и журнал отправок."""
from django.contrib import admin

from .models import NotificationLog, NotificationRecipient, NotificationRule


class NotificationRecipientInline(admin.TabularInline):
    """Получатели редактируются прямо на карточке правила."""

    model = NotificationRecipient
    extra = 1


@admin.register(NotificationRule)
class NotificationRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "event", "channel", "workshop", "threshold_percent", "is_active")
    list_filter = ("event", "channel", "is_active", "workshop")
    search_fields = ("name", "subject_template")
    inlines = [NotificationRecipientInline]


@admin.register(NotificationRecipient)
class NotificationRecipientAdmin(admin.ModelAdmin):
    list_display = ("email", "name", "rule", "is_active")
    list_filter = ("is_active", "rule")
    search_fields = ("email", "name")


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ("subject", "event", "channel", "status", "recipients", "sent_at", "created_at")
    list_filter = ("event", "channel", "status")
    search_fields = ("subject", "recipients", "error")
    date_hierarchy = "created_at"
    readonly_fields = (
        "rule", "event", "channel", "dedup_key", "recipients", "subject",
        "status", "error", "sent_at", "related_event", "related_case", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        # Журнал заполняется автоматически, вручную не создаём.
        return False
