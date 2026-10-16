"""Админка простоев и кейсов: ввод, фильтры, объединение и журнал изменений."""
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path

from .models import DowntimeCase, DowntimeCaseLog, DowntimeEvent, DowntimeEventLog, ReportingPeriod
from .services import (
    build_diff,
    create_case_from_events,
    find_duplicate_candidates,
    log_case,
    log_event,
    recalc_case,
    snapshot,
    case_snapshot,
)


# --- Журналы (только просмотр) ---

class DowntimeEventLogInline(admin.TabularInline):
    model = DowntimeEventLog
    extra = 0
    can_delete = False
    fields = ("created_at", "user", "action", "changes", "comment")
    readonly_fields = fields
    ordering = ("-created_at",)

    def has_add_permission(self, request, obj=None):
        return False


class DowntimeCaseLogInline(admin.TabularInline):
    model = DowntimeCaseLog
    extra = 0
    can_delete = False
    fields = ("created_at", "user", "action", "changes", "comment")
    readonly_fields = fields
    ordering = ("-created_at",)

    def has_add_permission(self, request, obj=None):
        return False


class DowntimeEventInline(admin.TabularInline):
    """Состав кейса — входящие события (только просмотр)."""

    model = DowntimeEvent
    fk_name = "case"
    extra = 0
    can_delete = False
    fields = ("started_at", "ended_at", "unit", "duration_min", "status")
    readonly_fields = fields
    ordering = ("started_at",)

    def has_add_permission(self, request, obj=None):
        return False


# --- Простои ---

@admin.register(DowntimeEvent)
class DowntimeEventAdmin(admin.ModelAdmin):
    change_list_template = "admin/downtimes/downtimeevent/change_list.html"
    list_display = (
        "started_at",
        "workshop",
        "unit",
        "duration_min",
        "status",
        "fault_side",
        "case",
        "sync_mark",
        "needs_review",
    )
    list_filter = (
        "needs_review",
        "sync_mark",
        "status",
        "fault_side",
        "source",
        "workshop",
        "fault_category",
        "case",
    )
    search_fields = ("note", "recorded_by_name", "external_id", "workshop__name", "unit__name")
    date_hierarchy = "started_at"
    autocomplete_fields = ("workshop", "section", "unit", "fault_category", "fault_subcategory", "case")
    readonly_fields = (
        "duration_min",
        "loss_display",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
        "source_key",
        "synced_at",
    )
    inlines = [DowntimeEventLogInline]
    actions = ["merge_into_case"]
    fieldsets = (
        ("Время", {"fields": ("started_at", "ended_at", "duration_min")}),
        ("Место", {"fields": ("workshop", "section", "unit")}),
        ("Вина", {"fields": ("service", "fault_side", "fault_category", "fault_subcategory")}),
        ("Описание", {"fields": ("note", "recorded_by_name")}),
        ("Потери", {"fields": ("unproduced_tons", "loss_display")}),
        ("Состояние и источник", {"fields": ("status", "source", "external_id")}),
        ("Синхронизация (11.6)", {"fields": ("sync_mark", "needs_review", "source_key", "synced_at")}),
        ("Объединение", {"fields": ("case",)}),
        (
            "Служебное",
            {
                "classes": ("collapse",),
                "fields": ("raw", "created_by", "updated_by", "created_at", "updated_at"),
            },
        ),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "duplicates/",
                self.admin_site.admin_view(self.duplicates_view),
                name="downtimes_duplicate_candidates",
            ),
        ]
        return custom + urls

    def duplicates_view(self, request):
        """Показывает группы похожих записей и объединяет выбранную группу в кейс."""
        if request.method == "POST":
            ids = request.POST.getlist("events")
            events = list(DowntimeEvent.objects.filter(id__in=ids))
            if len(events) >= 2:
                case = create_case_from_events(events, user=request.user)
                self.message_user(
                    request, f"Создан кейс {case.number} из {len(events)} событий."
                )
            else:
                self.message_user(request, "Нужно минимум 2 записи.", level=messages.WARNING)
            return redirect(request.path)

        context = {
            **self.admin_site.each_context(request),
            "title": "Возможные дубли",
            "groups": find_duplicate_candidates(),
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/downtimes/downtimeevent/duplicates.html", context)

    @admin.action(description="Объединить выбранные в один кейс")
    def merge_into_case(self, request, queryset):
        events = list(queryset)
        if len(events) < 2:
            self.message_user(request, "Выберите минимум 2 записи.", level=messages.WARNING)
            return
        case = create_case_from_events(events, user=request.user)
        self.message_user(request, f"Создан кейс {case.number} из {len(events)} событий.")

    @admin.display(description="Потери (расчёт)")
    def loss_display(self, obj):
        """Показывает расчёт потерь по простою. Считается на лету (см. apps.sla)."""
        if obj is None or obj.pk is None:
            return "—"
        from apps.sla.services import event_loss

        loss = event_loss(obj)
        if loss.missing_rate:
            return "нет ставки (не задан участок или ставка)"
        return f"{loss.amount} ₽"

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


# --- Кейсы ---

@admin.register(DowntimeCase)
class DowntimeCaseAdmin(admin.ModelAdmin):
    list_display = ("number", "title", "status", "started_at", "ended_at", "duration_min", "events_count")
    list_filter = ("status", "fault_side", "fault_category")
    search_fields = ("number", "title", "note", "fault_category__name")
    date_hierarchy = "started_at"
    autocomplete_fields = ("fault_category", "fault_subcategory")
    readonly_fields = (
        "number",
        "started_at",
        "ended_at",
        "duration_min",
        "loss_display",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )
    inlines = [DowntimeEventInline, DowntimeCaseLogInline]
    actions = ["recalc_selected"]
    fieldsets = (
        ("Кейс", {"fields": ("number", "title", "status")}),
        ("Вина", {"fields": ("fault_side", "fault_category", "fault_subcategory")}),
        ("Период и длительность", {"fields": ("started_at", "ended_at", "duration_min")}),
        ("Потери", {"fields": ("unproduced_tons", "loss_display")}),
        ("Описание", {"fields": ("note",)}),
        (
            "Служебное",
            {
                "classes": ("collapse",),
                "fields": ("created_by", "updated_by", "created_at", "updated_at"),
            },
        ),
    )

    @admin.display(description="Событий")
    def events_count(self, obj):
        return obj.events.count()

    @admin.display(description="Потери (расчёт)")
    def loss_display(self, obj):
        """Показывает расчёт потерь по кейсу (без двойного счёта). См. apps.sla."""
        if obj is None or obj.pk is None:
            return "—"
        from apps.sla.services import case_loss

        loss = case_loss(obj)
        text = f"{loss.amount} ₽"
        if loss.tons:
            text += f" · {loss.tons} т"
        if loss.missing_rate:
            text += " · нет ставки по части участков"
        return text

    @admin.action(description="Пересчитать длительность выбранных кейсов")
    def recalc_selected(self, request, queryset):
        for case in queryset:
            recalc_case(case)
        self.message_user(request, f"Пересчитано кейсов: {queryset.count()}.")

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        if not change:
            obj.created_by = request.user

        before = {} if not change else case_snapshot(DowntimeCase.objects.get(pk=obj.pk))
        super().save_model(request, obj, form, change)
        after = case_snapshot(obj)

        if not change:
            log_case(obj, request.user, DowntimeCaseLog.Action.CREATED)
            return

        changes = build_diff(before, after)
        if changes:
            action = (
                DowntimeCaseLog.Action.STATUS
                if "Статус" in changes
                else DowntimeCaseLog.Action.UPDATED
            )
            log_case(obj, request.user, action, changes)


# --- Отдельные страницы журналов (только просмотр) ---

@admin.register(DowntimeEventLog)
class DowntimeEventLogAdmin(admin.ModelAdmin):
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


@admin.register(DowntimeCaseLog)
class DowntimeCaseLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "case", "user", "action", "comment")
    list_filter = ("action", "created_at")
    search_fields = ("case__number", "case__title", "comment")
    date_hierarchy = "created_at"
    readonly_fields = ("case", "user", "action", "changes", "comment", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReportingPeriod)
class ReportingPeriodAdmin(admin.ModelAdmin):
    """Закрытые периоды (месяцы). Закрытие/открытие — супервайзерская операция."""

    list_display = ("year", "month", "closed_at", "closed_by", "note")
    list_filter = ("year",)
    ordering = ("-year", "-month")
    readonly_fields = ("closed_at", "created_at", "updated_at")
