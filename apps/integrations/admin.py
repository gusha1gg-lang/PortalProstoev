"""Админка модуля «Интеграции»: связи инцидентов с тикетами OMNITRACKER."""
from django.contrib import admin

from .models import TicketLink


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
