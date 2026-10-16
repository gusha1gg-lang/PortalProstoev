"""Тесты справочников (запуск: python manage.py test apps.catalog)."""
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import (
    Enterprise,
    ItFaultCategory,
    ItFaultSubcategory,
    LossRate,
    Section,
    Unit,
    Workshop,
)


class StructureUniqueTests(TestCase):
    """Названия уникальны в пределах родителя (по-простому: без повторов в одном месте)."""

    @classmethod
    def setUpTestData(cls):
        cls.enterprise = Enterprise.objects.create(name="Завод А")
        cls.other_enterprise = Enterprise.objects.create(name="Завод Б")
        cls.workshop = Workshop.objects.create(enterprise=cls.enterprise, name="Цех-1")
        cls.section = Section.objects.create(workshop=cls.workshop, name="Участок-1")

    def test_enterprise_name_is_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enterprise.objects.create(name="Завод А")

    def test_workshop_name_unique_inside_enterprise(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Workshop.objects.create(enterprise=self.enterprise, name="Цех-1")

    def test_same_workshop_name_allowed_in_another_enterprise(self):
        duplicated = Workshop.objects.create(enterprise=self.other_enterprise, name="Цех-1")
        self.assertEqual(duplicated.name, "Цех-1")

    def test_section_name_unique_inside_workshop(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Section.objects.create(workshop=self.workshop, name="Участок-1")

    def test_unit_name_unique_inside_section(self):
        Unit.objects.create(section=self.section, name="Агрегат-1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Unit.objects.create(section=self.section, name="Агрегат-1")

    def test_unit_default_criticality_is_medium(self):
        unit = Unit.objects.create(section=self.section, name="Агрегат-2")
        self.assertEqual(unit.criticality, Unit.Criticality.MEDIUM)


class FaultCategoryTests(TestCase):
    def test_category_code_is_unique(self):
        ItFaultCategory.objects.create(code="net", name="Сеть")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ItFaultCategory.objects.create(code="net", name="Сеть ещё раз")

    def test_subcategory_code_unique_inside_category(self):
        category = ItFaultCategory.objects.create(code="srv", name="Серверы")
        other = ItFaultCategory.objects.create(code="app", name="Приложения")
        ItFaultSubcategory.objects.create(category=category, code="cpu", name="Процессор")

        with self.assertRaises(IntegrityError), transaction.atomic():
            ItFaultSubcategory.objects.create(category=category, code="cpu", name="Процессор снова")

        # Тот же код в другой категории — можно.
        duplicated = ItFaultSubcategory.objects.create(category=other, code="cpu", name="Процессор")
        self.assertEqual(duplicated.code, "cpu")


class LossRateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        enterprise = Enterprise.objects.create(name="Завод")
        workshop = Workshop.objects.create(enterprise=enterprise, name="Цех")
        cls.section = Section.objects.create(workshop=workshop, name="Участок")

    def test_valid_to_before_valid_from_is_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            LossRate.objects.create(
                section=self.section,
                cost_per_hour=Decimal("1000"),
                valid_from=date(2026, 1, 1),
                valid_to=date(2025, 1, 1),
            )

    def test_open_ended_rate_is_allowed(self):
        rate = LossRate.objects.create(
            section=self.section, cost_per_hour=Decimal("120000"), valid_from=date(2026, 1, 1)
        )
        self.assertIsNone(rate.valid_to)

    def test_str_mentions_rate_and_period(self):
        rate = LossRate.objects.create(
            section=self.section, cost_per_hour=Decimal("5000"), valid_from=date(2026, 1, 1)
        )
        text = str(rate)
        self.assertIn("5000", text)
        self.assertIn("с 2026-01-01", text)


class DisplayTests(TestCase):
    def test_workshop_str_includes_enterprise(self):
        enterprise = Enterprise.objects.create(name="Завод А")
        workshop = Workshop.objects.create(enterprise=enterprise, name="Цех-1")
        self.assertEqual(str(workshop), "Завод А / Цех-1")

    def test_unit_str_includes_code_when_present(self):
        enterprise = Enterprise.objects.create(name="Завод А")
        workshop = Workshop.objects.create(enterprise=enterprise, name="Цех-1")
        section = Section.objects.create(workshop=workshop, name="Участок-1")
        unit = Unit.objects.create(section=section, name="Агрегат-1", code="A-1")
        self.assertEqual(str(unit), "Агрегат-1 (A-1)")
