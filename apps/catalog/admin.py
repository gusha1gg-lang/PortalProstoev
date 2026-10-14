"""Админка справочников: через неё справочники ведутся без программирования."""
from django.contrib import admin

from .models import (
    Equipment,
    ItFaultCategory,
    ItFaultSubcategory,
    LossRate,
    ProductionLine,
    Workshop,
)


class ProductionLineInline(admin.TabularInline):
    model = ProductionLine
    extra = 0


@admin.register(Workshop)
class WorkshopAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")
    inlines = [ProductionLineInline]


class EquipmentInline(admin.TabularInline):
    model = Equipment
    extra = 0


@admin.register(ProductionLine)
class ProductionLineAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "workshop", "is_active")
    list_filter = ("workshop", "is_active")
    search_fields = ("name", "code")
    inlines = [EquipmentInline]


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "line", "criticality", "is_active")
    list_filter = ("criticality", "line__workshop", "is_active")
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
    list_display = ("line", "cost_per_hour", "ton_margin", "valid_from", "valid_to")
    list_filter = ("line__workshop", "line")
    search_fields = ("line__name",)
    date_hierarchy = "valid_from"
