"""Регистрация модели разбора в стандартной админке Django."""
from django.contrib import admin

from .models import IncidentReview


@admin.register(IncidentReview)
class IncidentReviewAdmin(admin.ModelAdmin):
    list_display = ("number", "title", "status", "lead", "case", "created_at")
    list_filter = ("status",)
    search_fields = ("number", "title", "case__number")
    readonly_fields = ("number", "created_at", "updated_at")
