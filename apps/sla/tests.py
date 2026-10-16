"""Тесты расчёта потерь и SLA (запуск: python manage.py test apps.sla)."""
from datetime import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Enterprise, LossRate, Section, Unit, Workshop
from apps.downtimes.models import DowntimeEvent
from apps.downtimes.services import create_case_from_events

from .services import case_loss, event_loss, sla_summary


def dt(text):
    """Создаёт дату-время с часовым поясом из строки «ГГГГ-ММ-ДД ЧЧ:ММ»."""
    return timezone.make_aware(datetime.strptime(text, "%Y-%m-%d %H:%M"))


class LossTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.enterprise = Enterprise.objects.create(name='Тестовый завод')
        cls.workshop = Workshop.objects.create(enterprise=cls.enterprise, name="ТЭСЦ-4")
        cls.section_a = Section.objects.create(workshop=cls.workshop, name="Участок отделки")
        cls.section_b = Section.objects.create(workshop=cls.workshop, name="Участок сварки")
        LossRate.objects.create(section=cls.section_a, cost_per_hour=Decimal("120000"), valid_from="2025-01-01")
        LossRate.objects.create(section=cls.section_b, cost_per_hour=Decimal("90000"), valid_from="2025-01-01")

    def make_event(self, section, start, end, tons="0", status=DowntimeEvent.Status.CONFIRMED):
        return DowntimeEvent.objects.create(
            started_at=dt(start),
            ended_at=dt(end),
            workshop=self.workshop,
            section=section,
            unproduced_tons=Decimal(tons),
            status=status,
            fault_side=DowntimeEvent.FaultSide.IT,
        )


class EventLossTests(LossTestBase):
    def test_event_loss_is_hours_times_rate(self):
        event = self.make_event(self.section_a, "2026-10-10 15:00", "2026-10-10 15:30")
        loss = event_loss(event)
        # 0,5 часа × 120 000 = 60 000
        self.assertEqual(loss.amount, Decimal("60000.00"))

    def test_event_tons_do_not_affect_amount(self):
        """Тонны больше не влияют на деньги: потери = часы × ставка (В2)."""
        event = self.make_event(self.section_a, "2026-10-10 15:00", "2026-10-10 15:30", tons="10")
        loss = event_loss(event)
        # 0,5 часа × 120 000 = 60 000 (тонны в расчёте денег не участвуют).
        self.assertEqual(loss.amount, Decimal("60000.00"))
        self.assertEqual(loss.tons, Decimal("10"))

    def test_missing_rate_is_flagged(self):
        event = self.make_event(None, "2026-10-10 15:00", "2026-10-10 15:30")
        loss = event_loss(event)
        self.assertTrue(loss.missing_rate)
        self.assertEqual(loss.amount, Decimal("0.00"))


class CaseLossTests(LossTestBase):
    def test_overlapping_events_count_once(self):
        """Два события по 15 минут внахлёст — считаем 15 минут, а не 30."""
        e1 = self.make_event(self.section_a, "2026-10-10 15:05", "2026-10-10 15:20")
        e2 = self.make_event(self.section_a, "2026-10-10 15:05", "2026-10-10 15:20")
        case = create_case_from_events([e1, e2], user=None)
        loss = case_loss(case)
        # 0,25 часа × 120 000 = 30 000 (а не 60 000)
        self.assertEqual(loss.amount, Decimal("30000.00"))

    def test_case_sums_sections_without_double_count(self):
        """Разные участки считаются каждый по своему времени и ставке."""
        e1 = self.make_event(self.section_a, "2026-10-10 15:00", "2026-10-10 15:30")
        e2 = self.make_event(self.section_b, "2026-10-10 15:10", "2026-10-10 15:40")
        case = create_case_from_events([e1, e2], user=None)
        loss = case_loss(case)
        # отделка: 0,5 × 120 000 = 60 000; сварка: 0,5 × 90 000 = 45 000
        self.assertEqual(loss.amount, Decimal("105000.00"))


class AvailabilityTests(LossTestBase):
    def test_availability_and_mttr(self):
        self.make_event(self.section_a, "2026-10-10 15:00", "2026-10-10 15:30")  # 30 мин
        summary = sla_summary(self.enterprise, 2026, 10)
        self.assertEqual(summary["incident_count"], 1)
        self.assertEqual(summary["downtime_min"], 30)
        self.assertEqual(summary["mttr_min"], Decimal("30.0"))
        # Доступность очень высокая (30 минут за месяц).
        self.assertLess(summary["availability"], Decimal("100.00"))
        self.assertGreater(summary["availability"], Decimal("99.00"))

    def test_canceled_events_are_ignored(self):
        self.make_event(
            self.section_a,
            "2026-10-10 15:00",
            "2026-10-10 15:30",
            status=DowntimeEvent.Status.CANCELED,
        )
        summary = sla_summary(self.enterprise, 2026, 10)
        self.assertEqual(summary["incident_count"], 0)
        self.assertEqual(summary["availability"], Decimal("100.00"))
