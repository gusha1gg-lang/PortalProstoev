"""Админка справочников: через неё справочники ведутся без программирования."""
from django.contrib import admin

from .models import (
    Enterprise,
    ItFaultCategory,
    ItFaultSubcategory,
    LossRate,
    Section,
    Unit,
    Workshop,
)


class WorkshopInline(admin.TabularInline):
    model = Workshop
    extra = 0


@admin.register(Enterprise)
class EnterpriseAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")
    inlines = [WorkshopInline]


class SectionInline(admin.TabularInline):
    model = Section
    extra = 0


@admin.register(Workshop)
class WorkshopAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "enterprise", "is_active")
    list_filter = ("enterprise", "is_active")
    search_fields = ("name", "code")
    inlines = [SectionInline]


class UnitInline(admin.TabularInline):
    model = Unit
    extra = 0
    # Участок задаёт родитель (Section), цех выводится из участка — их не показываем.
    fields = ("name", "code", "criticality", "is_active")


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "workshop", "is_active")
    list_filter = ("workshop__enterprise", "workshop", "is_active")
    search_fields = ("name", "code")
    inlines = [UnitInline]


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "workshop", "section", "criticality", "is_active")
    list_filter = ("criticality", "workshop", "is_active")
    search_fields = ("name", "code")


class ItFaultSubcategoryInline(admin.TabularInline):
    model = ItFaultSubcategory
    extra = 0


@admin.register(ItFaultCategory)
class ItFaultCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")
    inlines = [ItFaultSubcategoryInline]


@admin.register(ItFaultSubcategory)
class ItFaultSubcategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "category", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name", "code")


@admin.register(LossRate)
class LossRateAdmin(admin.ModelAdmin):
    list_display = ("section", "cost_per_hour", "valid_from", "valid_to")
    list_filter = ("section__workshop__enterprise", "section")
    search_fields = ("section__name",)
    date_hierarchy = "valid_from"
