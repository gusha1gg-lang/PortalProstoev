"""Админка простоев: ввод, фильтры, поиск и просмотр журнала изменений."""
from django.contrib import admin

from .models import DowntimeEvent, DowntimeEventLog
from .services import build_diff, log_event, snapshot


class DowntimeEventLogInline(admin.TabularInline):
    """История изменений прямо на карточке простоя. Только для чтения."""

    model = DowntimeEventLog
    extra = 0
    can_delete = False
    fields = ("created_at", "user", "action", "changes", "comment")
    readonly_fields = ("created_at", "user", "action", "changes", "comment")
    ordering = ("-created_at",)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DowntimeEvent)
class DowntimeEventAdmin(admin.ModelAdmin):
    list_display = (
        "started_at",
        "workshop",
        "unit",
        "duration_min",
        "status",
        "fault_side",
        "fault_category",
    )
    list_filter = (
        "status",
        "fault_side",
        "source",
        "workshop__enterprise",
        "workshop",
        "fault_category",
    )
    search_fields = ("note", "recorded_by_name", "external_id", "workshop__name", "unit__name")
    date_hierarchy = "started_at"
    autocomplete_fields = (
        "workshop",
        "section",
        "unit",
        "fault_category",
        "fault_subcategory",
    )
    readonly_fields = ("duration_min", "created_by", "updated_by", "created_at", "updated_at")
    inlines = [DowntimeEventLogInline]
    fieldsets = (
        ("Время", {"fields": ("started_at", "ended_at", "duration_min")}),
        ("Место", {"fields": ("workshop", "section", "unit")}),
        (
            "Вина",
            {"fields": ("service", "fault_side", "fault_category", "fault_subcategory")},
        ),
        ("Описание", {"fields": ("note", "recorded_by_name")}),
        (
            "Состояние и источник",
            {"fields": ("status", "source", "external_id")},
        ),
        (
            "Служебное",
            {
                "classes": ("collapse",),
                "fields": ("raw", "created_by", "updated_by", "created_at", "updated_at"),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        """Сохраняем и пишем журнал: создание отдельной записью, изменения — если есть."""
        obj.updated_by = request.user
        if not change:
            obj.created_by = request.user

        before = {} if not change else snapshot(DowntimeEvent.objects.get(pk=obj.pk))
        super().save_model(request, obj, form, change)
        after = snapshot(obj)

        if not change:
            log_event(obj, request.user, DowntimeEventLog.Action.CREATED)
            return

        changes = build_diff(before, after)
        if changes:
            action = (
                DowntimeEventLog.Action.STATUS
                if "Статус" in changes
                else DowntimeEventLog.Action.UPDATED
            )
            log_event(obj, request.user, action, changes)


@admin.register(DowntimeEventLog)
class DowntimeEventLogAdmin(admin.ModelAdmin):
    """Отдельная страница журнала — только просмотр."""

    list_display = ("created_at", "event", "user", "action", "comment")
    list_filter = ("action", "created_at")
    search_fields = ("event__note", "comment")
    date_hierarchy = "created_at"
    readonly_fields = ("event", "user", "action", "changes", "comment", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
