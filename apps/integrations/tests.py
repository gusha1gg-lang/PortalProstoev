"""Тесты интеграций: импорт простоев и связь с тикетами (python manage.py test apps.integrations)."""
from django.test import TestCase

from apps.catalog.models import Section, Unit, Workshop
from apps.downtimes.models import DowntimeEvent

from .models import TicketLink
from .omnitracker import MockOmniTracker, Ticket
from .saarc import MOCK_ROWS, MockSaarcSource, SourceRow
from .services import (
    fetch_tickets,
    import_downtimes,
    link_ticket,
    parse_dt,
    row_fingerprint,
    row_is_ours,
    sync_tickets,
)


class ImportTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        workshop = Workshop.objects.create(name="ТЭСЦ-4")
        ot = Section.objects.create(workshop=workshop, name="Участок отделки труб 1020")
        sv = Section.objects.create(workshop=workshop, name="Участок сварки труб 1020")
        Unit.objects.create(section=ot, name="Площадка №9 окончательной приемки — ОПТ №9")
        Unit.objects.create(section=ot, name="Участок АУЗК-31 — АУЗК-31")
        Unit.objects.create(section=sv, name="Ремонтная площадка №3 — ССС-3")


class RowHelpersTests(TestCase):
    def test_parse_dt_with_seconds(self):
        value = parse_dt("2026-10-10 15:01:25")
        self.assertEqual(value.year, 2026)
        self.assertEqual(value.minute, 1)

    def test_row_is_ours_filters_by_service(self):
        self.assertTrue(row_is_ours({"СЛУЖБА": "ДИТ"}))
        self.assertTrue(row_is_ours({"СЛУЖБА": " дит "}))
        self.assertFalse(row_is_ours({"СЛУЖБА": "Энергоцех"}))

    def test_fingerprint_is_stable_and_distinct(self):
        row_a = dict(MOCK_ROWS[0])
        row_a_copy = dict(MOCK_ROWS[0])
        self.assertEqual(row_fingerprint(row_a), row_fingerprint(row_a_copy))

        row_b = dict(MOCK_ROWS[0])
        row_b["КОНЕЦ"] = "2026-09-20 10:21:00"
        self.assertNotEqual(row_fingerprint(row_a), row_fingerprint(row_b))


class ImportTests(ImportTestBase):
    def test_import_creates_ours_and_skips_others(self):
        report = import_downtimes(source=MockSaarcSource())
        # 3 строки ДИТ с известными справочниками, 1 чужая служба, 1 незнакомый цех
        self.assertEqual(report.total, 5)
        self.assertEqual(report.created, 3)
        self.assertEqual(report.filtered_out, 1)
        self.assertEqual(report.skipped_missing, 1)
        self.assertEqual(DowntimeEvent.objects.filter(source=DowntimeEvent.Source.SAARC).count(), 3)

    def test_import_is_idempotent(self):
        import_downtimes(source=MockSaarcSource())
        second = import_downtimes(source=MockSaarcSource())
        self.assertEqual(second.created, 0)
        self.assertEqual(second.skipped_existing, 3)
        self.assertEqual(DowntimeEvent.objects.filter(source=DowntimeEvent.Source.SAARC).count(), 3)

    def test_imported_event_is_it_and_new(self):
        import_downtimes(source=MockSaarcSource())
        event = DowntimeEvent.objects.filter(source=DowntimeEvent.Source.SAARC).first()
        self.assertEqual(event.fault_side, DowntimeEvent.FaultSide.IT)
        self.assertEqual(event.status, DowntimeEvent.Status.NEW)
        self.assertEqual(event.service, "ДИТ")
        self.assertIsNotNone(event.section)

    def test_problem_row_is_reported(self):
        report = import_downtimes(source=MockSaarcSource())
        text = report.as_text()
        self.assertIn("НЕИЗВЕСТНЫЙ ЦЕХ", "\n".join(report.problems))
        self.assertIn("создано", text)


class TicketTests(ImportTestBase):
    def test_mock_tickets_are_fetched(self):
        tickets = fetch_tickets()
        self.assertGreaterEqual(len(tickets), 2)

    def test_link_and_sync_ticket(self):
        event = DowntimeEvent.objects.create(
            started_at=parse_dt("2026-10-10 15:00:00"),
            ended_at=parse_dt("2026-10-10 15:30:00"),
            workshop=Workshop.objects.first(),
        )
        ticket = Ticket(external_id="INC-100500", title="Не работает система ДМАП", status="В работе")
        link = link_ticket(ticket, event=event)
        self.assertEqual(TicketLink.objects.count(), 1)
        self.assertEqual(link.external_id, "INC-100500")

        summary = sync_tickets(source=MockOmniTracker())
        self.assertEqual(summary["linked"], 1)
        self.assertGreaterEqual(summary["updated"], 1)
