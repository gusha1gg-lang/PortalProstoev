"""Тесты справочников (запуск: python manage.py test apps.catalog)."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.roles import (
    ALL_ROLES,
    ROLE_DOWNTIME_SPECIALIST,
    ROLE_IT_MANAGER,
    ROLE_OPERATOR,
)

from .models import (
    ItFaultCategory,
    ItFaultSubcategory,
    LossRate,
    Section,
    Unit,
    Workshop,
)

HOST = {"HTTP_HOST": "localhost"}


class StructureUniqueTests(TestCase):
    """Названия уникальны в пределах родителя (по-простому: без повторов в одном месте)."""

    @classmethod
    def setUpTestData(cls):
        cls.workshop = Workshop.objects.create(name="Цех-1")
        cls.section = Section.objects.create(workshop=cls.workshop, name="Участок-1")

    def test_workshop_name_is_unique(self):
        """Уровень «Предприятие» убран — название цеха уникально везде."""
        with self.assertRaises(IntegrityError), transaction.atomic():
            Workshop.objects.create(name="Цех-1")

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

    def test_unit_workshop_is_derived_from_section(self):
        """Цех агрегата выводится из участка автоматически (В1)."""
        unit = Unit.objects.create(section=self.section, name="Агрегат-3")
        self.assertEqual(unit.workshop_id, self.workshop.id)

    def test_sectionless_unit_is_attached_to_workshop(self):
        """Общецеховой агрегат можно завести без участка — прямо на цех (В1)."""
        unit = Unit.objects.create(workshop=self.workshop, name="Компрессор цеха")
        self.assertIsNone(unit.section)
        self.assertEqual(unit.workshop_id, self.workshop.id)

    def test_sectionless_unit_name_unique_inside_workshop(self):
        Unit.objects.create(workshop=self.workshop, name="Компрессор цеха")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Unit.objects.create(workshop=self.workshop, name="Компрессор цеха")


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
        workshop = Workshop.objects.create(name="Цех")
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
    def test_workshop_str_is_its_name(self):
        workshop = Workshop.objects.create(name="Цех-1")
        self.assertEqual(str(workshop), "Цех-1")

    def test_unit_str_includes_code_when_present(self):
        workshop = Workshop.objects.create(name="Цех-1")
        section = Section.objects.create(workshop=workshop, name="Участок-1")
        unit = Unit.objects.create(section=section, name="Агрегат-1", code="A-1")
        self.assertEqual(str(unit), "Агрегат-1 (A-1)")


class ClassificationViewTests(TestCase):
    """Редактор классификации вины ИТ прямо в портале (этап 11.6)."""

    @classmethod
    def setUpTestData(cls):
        for role in ALL_ROLES:
            Group.objects.get_or_create(name=role)
        # Названия причин/категорий в тестах — вымышленные (репозиторий публичный).
        cls.category = ItFaultCategory.objects.create(code="ARM", name="АРМ")
        cls.reason = ItFaultSubcategory.objects.create(
            category=cls.category, code="ARM-01", name="Причина-1"
        )

    def _user(self, username, role=None):
        user = get_user_model().objects.create_user(username=username, password="x")
        if role:
            user.groups.add(Group.objects.get(name=role))
        return user

    def test_page_denied_without_role(self):
        self.client.force_login(self._user("nobody", role=ROLE_OPERATOR))
        response = self.client.get("/catalog/", **HOST)
        self.assertEqual(response.status_code, 403)

    def test_page_allowed_for_it_manager(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        response = self.client.get("/catalog/", **HOST)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "АРМ")

    def test_add_category(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        response = self.client.post(
            "/catalog/category/add/",
            {"code": "INFRA", "name": "Инфраструктура", "description": "Сеть и серверы"},
            **HOST,
        )
        self.assertEqual(response.status_code, 302)
        category = ItFaultCategory.objects.get(code="INFRA")
        self.assertTrue(category.is_active)

    def test_add_category_duplicate_code_rejected(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        self.client.post(
            "/catalog/category/add/", {"code": "ARM", "name": "Ещё раз"}, **HOST
        )
        self.assertEqual(ItFaultCategory.objects.filter(code="ARM").count(), 1)

    def test_edit_category_renames(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        response = self.client.post(
            f"/catalog/category/{self.category.pk}/",
            {"name": "Новое имя", "description": "", "is_active": "on"},
            **HOST,
        )
        self.assertEqual(response.status_code, 302)
        self.category.refresh_from_db()
        self.assertEqual(self.category.name, "Новое имя")
        self.assertTrue(self.category.is_active)

    def test_toggle_category_hides_without_deleting(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        self.client.post(f"/catalog/category/{self.category.pk}/toggle/", **HOST)
        self.category.refresh_from_db()
        self.assertFalse(self.category.is_active)
        # Не удаляем — можно вернуть обратно.
        self.client.post(f"/catalog/category/{self.category.pk}/toggle/", **HOST)
        self.category.refresh_from_db()
        self.assertTrue(self.category.is_active)
        self.assertEqual(ItFaultCategory.objects.count(), 1)

    def test_add_reason_assigns_next_code(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        response = self.client.post(
            f"/catalog/category/{self.category.pk}/reason/add/",
            {"name": "Причина-2"},
            **HOST,
        )
        self.assertEqual(response.status_code, 302)
        reason = ItFaultSubcategory.objects.get(category=self.category, name="Причина-2")
        self.assertEqual(reason.code, "ARM-02")
        self.assertTrue(reason.is_active)

    def test_edit_reason_renames(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        self.client.post(
            f"/catalog/reason/{self.reason.pk}/edit/", {"name": "Переименовано"}, **HOST
        )
        self.reason.refresh_from_db()
        self.assertEqual(self.reason.name, "Переименовано")

    def test_toggle_reason_hides_without_deleting(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        self.client.post(f"/catalog/reason/{self.reason.pk}/toggle/", **HOST)
        self.reason.refresh_from_db()
        self.assertFalse(self.reason.is_active)
        self.assertEqual(ItFaultSubcategory.objects.count(), 1)

    def test_specialist_can_edit_classification(self):
        self.client.force_login(self._user("sp", role=ROLE_DOWNTIME_SPECIALIST))
        response = self.client.get("/catalog/", **HOST)
        self.assertEqual(response.status_code, 200)


class StructureEditorTests(TestCase):
    """Ручная правка производственной структуры в портале (план 11.6, В9)."""

    @classmethod
    def setUpTestData(cls):
        for role in ALL_ROLES:
            Group.objects.get_or_create(name=role)
        cls.workshop = Workshop.objects.create(name="Цех-42")
        cls.section = Section.objects.create(workshop=cls.workshop, name="Участок-1")
        cls.unit = Unit.objects.create(
            section=cls.section, name="Агрегат-1", criticality=Unit.Criticality.MEDIUM
        )

    def _user(self, username, role=None):
        user = get_user_model().objects.create_user(username=username, password="x")
        if role:
            user.groups.add(Group.objects.get(name=role))
        return user

    def test_structure_page_denied_without_role(self):
        self.client.force_login(self._user("nobody", role=ROLE_OPERATOR))
        response = self.client.get("/catalog/structure/", **HOST)
        self.assertEqual(response.status_code, 403)

    def test_structure_page_allowed_for_it_manager(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        response = self.client.get("/catalog/structure/", **HOST)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Цех-42")

    def test_add_workshop(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        response = self.client.post(
            "/catalog/structure/workshop/add/", {"name": "Цех-43", "code": "C43"}, **HOST
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Workshop.objects.filter(name="Цех-43", code="C43", is_active=True).exists())

    def test_add_workshop_duplicate_name_rejected(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        self.client.post("/catalog/structure/workshop/add/", {"name": "Цех-42"}, **HOST)
        self.assertEqual(Workshop.objects.filter(name="Цех-42").count(), 1)

    def test_edit_workshop_renames(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        self.client.post(
            f"/catalog/structure/workshop/{self.workshop.pk}/",
            {"name": "Цех-42 переименован", "code": "C42", "is_active": "on"},
            **HOST,
        )
        self.workshop.refresh_from_db()
        self.assertEqual(self.workshop.name, "Цех-42 переименован")
        self.assertTrue(self.workshop.is_active)

    def test_toggle_workshop_hides_without_deleting(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        self.client.post(f"/catalog/structure/workshop/{self.workshop.pk}/toggle/", **HOST)
        self.workshop.refresh_from_db()
        self.assertFalse(self.workshop.is_active)
        self.client.post(f"/catalog/structure/workshop/{self.workshop.pk}/toggle/", **HOST)
        self.workshop.refresh_from_db()
        self.assertTrue(self.workshop.is_active)
        self.assertEqual(Workshop.objects.count(), 1)

    def test_add_section_to_workshop(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        self.client.post(
            f"/catalog/structure/workshop/{self.workshop.pk}/section/add/",
            {"name": "Участок-2"},
            **HOST,
        )
        self.assertTrue(
            Section.objects.filter(workshop=self.workshop, name="Участок-2").exists()
        )

    def test_duplicate_section_in_same_workshop_rejected(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        self.client.post(
            f"/catalog/structure/workshop/{self.workshop.pk}/section/add/",
            {"name": "Участок-1"},
            **HOST,
        )
        self.assertEqual(Section.objects.filter(workshop=self.workshop, name="Участок-1").count(), 1)

    def test_add_section_allowed_with_same_name_in_other_workshop(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        other = Workshop.objects.create(name="Цех-44")
        self.client.post(
            f"/catalog/structure/workshop/{other.pk}/section/add/", {"name": "Участок-1"}, **HOST
        )
        self.assertTrue(Section.objects.filter(workshop=other, name="Участок-1").exists())

    def test_edit_section_renames(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        self.client.post(
            f"/catalog/structure/section/{self.section.pk}/",
            {"name": "Участок-1 новый", "code": "", "is_active": "on"},
            **HOST,
        )
        self.section.refresh_from_db()
        self.assertEqual(self.section.name, "Участок-1 новый")

    def test_toggle_section_redirects_to_its_workshop(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        response = self.client.post(
            f"/catalog/structure/section/{self.section.pk}/toggle/", **HOST
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith(f"/catalog/structure/workshop/{self.workshop.pk}/"))
        self.section.refresh_from_db()
        self.assertFalse(self.section.is_active)

    def test_add_unit_to_section_with_criticality(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        self.client.post(
            f"/catalog/structure/section/{self.section.pk}/unit/add/",
            {"name": "Агрегат-2", "criticality": "critical"},
            **HOST,
        )
        unit = Unit.objects.get(section=self.section, name="Агрегат-2")
        self.assertEqual(unit.criticality, Unit.Criticality.CRITICAL)
        # Цех агрегата выводится из участка автоматически (В1).
        self.assertEqual(unit.workshop_id, self.workshop.pk)

    def test_duplicate_unit_in_same_section_rejected(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        self.client.post(
            f"/catalog/structure/section/{self.section.pk}/unit/add/",
            {"name": "Агрегат-1"},
            **HOST,
        )
        self.assertEqual(Unit.objects.filter(section=self.section, name="Агрегат-1").count(), 1)

    def test_add_sectionless_workshop_unit(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        self.client.post(
            f"/catalog/structure/workshop/{self.workshop.pk}/unit/add/",
            {"name": "Компрессорная цеха", "criticality": "high"},
            **HOST,
        )
        unit = Unit.objects.get(workshop=self.workshop, section=None, name="Компрессорная цеха")
        self.assertEqual(unit.criticality, Unit.Criticality.HIGH)

    def test_edit_unit_renames_and_changes_criticality(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        self.client.post(
            f"/catalog/structure/unit/{self.unit.pk}/edit/",
            {"name": "Агрегат-1 новый", "criticality": "low"},
            **HOST,
        )
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.name, "Агрегат-1 новый")
        self.assertEqual(self.unit.criticality, Unit.Criticality.LOW)

    def test_toggle_unit_hides_without_deleting(self):
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        self.client.post(f"/catalog/structure/unit/{self.unit.pk}/toggle/", **HOST)
        self.unit.refresh_from_db()
        self.assertFalse(self.unit.is_active)
        self.assertEqual(Unit.objects.count(), 1)
