"""Регистрация моделей модуля разбора в стандартной админке Django."""
from django.contrib import admin

from .models import (
    ActionTemplate,
    IncidentReview,
    ReviewAction,
    ReviewApproval,
    ReviewLog,
    ReviewMessage,
    ReviewParticipant,
    TimelineEntry,
)


class TimelineEntryInline(admin.TabularInline):
    model = TimelineEntry
    extra = 0


class ReviewParticipantInline(admin.TabularInline):
    model = ReviewParticipant
    extra = 0


@admin.register(IncidentReview)
class IncidentReviewAdmin(admin.ModelAdmin):
    list_display = ("number", "title", "status", "lead", "case", "created_at")
    list_filter = ("status",)
    search_fields = ("number", "title", "case__number")
    readonly_fields = ("number", "created_at", "updated_at")
    inlines = [TimelineEntryInline, ReviewParticipantInline]


@admin.register(ReviewMessage)
class ReviewMessageAdmin(admin.ModelAdmin):
    list_display = ("review", "author", "created_at")
    search_fields = ("text", "review__number")


@admin.register(ReviewLog)
class ReviewLogAdmin(admin.ModelAdmin):
    list_display = ("review", "action", "user", "created_at")
    list_filter = ("action",)


@admin.register(ReviewAction)
class ReviewActionAdmin(admin.ModelAdmin):
    list_display = ("review", "title", "status", "due_at")
    list_filter = ("status",)
    search_fields = ("title", "review__number")
    filter_horizontal = ("assignees",)


@admin.register(ActionTemplate)
class ActionTemplateAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "order", "is_active")
    list_filter = ("is_active", "category")
    search_fields = ("title", "description")


@admin.register(ReviewApproval)
class ReviewApprovalAdmin(admin.ModelAdmin):
    list_display = ("review", "user", "decision", "decided_at")
    list_filter = ("decision",)
    search_fields = ("review__number", "user__username")
