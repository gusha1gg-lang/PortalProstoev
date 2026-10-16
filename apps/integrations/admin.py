"""Админка модуля «Интеграции»: связи инцидентов с тикетами и запуски синхронизации."""
from django.contrib import admin

from .models import SyncRun, TicketLink


@admin.register(TicketLink)
class TicketLinkAdmin(admin.ModelAdmin):
    list_display = ("external_id", "title", "status", "source", "target", "synced_at")
    list_filter = ("source", "status")
    search_fields = ("external_id", "title", "case__number", "case__title", "event__note")
    autocomplete_fields = ("event", "case")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="К чему привязан")
    def target(self, obj):
        return obj.case or obj.event or "—"


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    """Журнал запусков синхронизации (в основном просмотр + полный отчёт)."""

    list_display = (
        "started_at",
        "mode",
        "status",
        "user",
        "total",
        "created",
        "corrected",
        "adjusted",
        "removed",
        "skipped_closed",
        "changed",
    )
    list_filter = ("mode", "status")
    date_hierarchy = "started_at"
    ordering = ("-started_at",)
    readonly_fields = (
        "mode",
        "status",
        "started_at",
        "finished_at",
        "since",
        "until",
        "user",
        "total",
        "created",
        "corrected",
        "adjusted",
        "removed",
        "skipped_closed",
        "filtered_out",
        "skipped_missing",
        "report",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False  # запуски создаёт только сама синхронизация
