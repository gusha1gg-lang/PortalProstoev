"""Админка модуля «Потери и SLA»: ведение договоров SLA."""
from django.contrib import admin

from .models import SlaContract


@admin.register(SlaContract)
class SlaContractAdmin(admin.ModelAdmin):
    list_display = (
        "workshop",
        "name",
        "target_availability",
        "penalty_per_hour",
        "valid_from",
        "valid_to",
        "is_active",
    )
    list_filter = ("workshop", "is_active")
    search_fields = ("name", "workshop__name")
    date_hierarchy = "valid_from"
    fieldsets = (
        ("Договор", {"fields": ("workshop", "name", "is_active")}),
        ("Условия", {"fields": ("target_availability", "penalty_per_hour")}),
        ("Срок действия", {"fields": ("valid_from", "valid_to")}),
        ("Прочее", {"fields": ("note",)}),
    )
