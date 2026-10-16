"""Тесты интеграций: импорт простоев и связь с тикетами (python manage.py test apps.integrations)."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone

from apps.accounts.roles import (
    ALL_ROLES,
    ROLE_DOWNTIME_SPECIALIST,
    ROLE_IT_MANAGER,
)
from apps.catalog.models import Section, Unit, Workshop
from apps.downtimes.models import DowntimeEvent, ReportingPeriod

from .models import SyncRun, TicketLink
from .omnitracker import MockOmniTracker, Ticket
from .saarc import MOCK_ROWS, MockSaarcSource, SourceRow
from .services import (
    fetch_tickets,
    import_downtimes,
    link_ticket,
    month_bounds,
    parse_dt,
    row_fingerprint,
    row_is_ours,
    source_key,
    sync_downtimes,
    sync_tickets,
)

HOST = {"HTTP_HOST": "localhost"}


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


# --- Синхронизация (этап 11.6) ---


class FakeSource:
    """Источник с изменяемым списком строк — имитирует правки и снятия в СААРЦ.

    В отличие от MockSaarcSource игнорирует окно since/until (строки задаются тестом),
    поэтому тесты управляют тем, «что сейчас видит источник».
    """

    def __init__(self, rows):
        self.rows = [dict(row) for row in rows]

    def fetch_rows(self, since=None, until=None):
        return [SourceRow(dict(row)) for row in self.rows]


class SyncTestBase(TestCase):
    """База: справочники как в ImportTestBase + окно сентября и 3 наши строки источника."""

    @classmethod
    def setUpTestData(cls):
        workshop = Workshop.objects.create(name="ТЭСЦ-4")
        ot = Section.objects.create(workshop=workshop, name="Участок отделки труб 1020")
        sv = Section.objects.create(workshop=workshop, name="Участок сварки труб 1020")
        Unit.objects.create(section=ot, name="Площадка №9 окончательной приемки — ОПТ №9")
        Unit.objects.create(section=ot, name="Участок АУЗК-31 — АУЗК-31")
        Unit.objects.create(section=sv, name="Ремонтная площадка №3 — ССС-3")

    def setUp(self):
        self.since, self.until = month_bounds(2026, 9)
        # Три наши (ДИТ) строки со известными справочниками.
        self.source = FakeSource([MOCK_ROWS[0], MOCK_ROWS[1], MOCK_ROWS[2]])

    def sync(self, source=None, since=None, until=None, mode=SyncRun.Mode.MANUAL):
        return sync_downtimes(
            since=self.since if since is None else since,
            until=self.until if until is None else until,
            mode=mode,
            source=source if source is not None else self.source,
            notify=False,
        )

    def event_by_row(self, row):
        return DowntimeEvent.objects.filter(source_key=source_key(row)).first()


class SourceKeyTests(TestCase):
    def test_end_time_change_keeps_key(self):
        row = dict(MOCK_ROWS[0])
        before = source_key(row)
        row["КОНЕЦ"] = "2026-09-20 11:59:00"
        row["ПРИМЕЧАНИЕ"] = "совсем другое"
        self.assertEqual(source_key(row), before)

    def test_start_time_change_changes_key(self):
        row = dict(MOCK_ROWS[0])
        before = source_key(row)
        row["НАЧАЛО"] = "2026-09-20 12:00:00"
        self.assertNotEqual(source_key(row), before)


class SyncTests(SyncTestBase):
    def test_first_sync_creates_events(self):
        report, run = self.sync()
        self.assertEqual(report.created, 3)
        self.assertEqual(report.review, 0)
        events = DowntimeEvent.objects.filter(source=DowntimeEvent.Source.SAARC)
        self.assertEqual(events.count(), 3)
        self.assertTrue(all(e.source_key for e in events))
        self.assertTrue(all(not e.needs_review for e in events))
        self.assertEqual(run.status, SyncRun.Status.OK)
        self.assertEqual(run.created, 3)
        self.assertEqual(SyncRun.objects.count(), 1)

    def test_sync_is_idempotent_when_nothing_changed(self):
        self.sync()
        report, run = self.sync()
        self.assertEqual(report.created, 0)
        self.assertEqual(report.unchanged, 3)
        self.assertEqual(report.review, 0)
        self.assertEqual(DowntimeEvent.objects.filter(source=DowntimeEvent.Source.SAARC).count(), 3)

    def test_sync_adopts_record_imported_without_source_key(self):
        # Эмуляция старого импорта: запись есть (external_id = отпечаток), но source_key пуст.
        row = self.source.rows[0]
        old = DowntimeEvent.objects.create(
            source=DowntimeEvent.Source.SAARC,
            external_id=row_fingerprint(row),
            started_at=parse_dt(row["НАЧАЛО"]),
            ended_at=parse_dt(row["КОНЕЦ"]),
            workshop=Workshop.objects.get(name="ТЭСЦ-4"),
            note=row["ПРИМЕЧАНИЕ"],
            recorded_by_name=row["ФИО"],
            status=DowntimeEvent.Status.NEW,
        )
        report, _run = self.sync()
        # Старая запись «усыновлена» — дубль не создан, уникальность не нарушена.
        self.assertEqual(DowntimeEvent.objects.filter(source=DowntimeEvent.Source.SAARC).count(), 3)
        self.assertEqual(report.created, 2)
        old.refresh_from_db()
        self.assertEqual(old.source_key, source_key(row))

    def test_changed_end_time_marks_adjusted_and_review(self):
        self.sync()
        self.source.rows[0]["КОНЕЦ"] = "2026-09-20 10:21:00"
        report, _run = self.sync()
        self.assertEqual(report.adjusted, 1)
        self.assertEqual(report.corrected, 0)
        event = self.event_by_row(self.source.rows[0])
        self.assertTrue(event.needs_review)
        self.assertEqual(event.sync_mark, DowntimeEvent.SyncMark.ADJUSTED)
        self.assertEqual(event.ended_at.minute, 21)
        # Запись не удалена и не задублирована.
        self.assertEqual(DowntimeEvent.objects.filter(source=DowntimeEvent.Source.SAARC).count(), 3)

    def test_changed_note_marks_corrected(self):
        self.sync()
        self.source.rows[0]["ПРИМЕЧАНИЕ"] = "Новое описание"
        report, _run = self.sync()
        self.assertEqual(report.corrected, 1)
        event = self.event_by_row(self.source.rows[0])
        self.assertEqual(event.sync_mark, DowntimeEvent.SyncMark.CORRECTED)
        self.assertEqual(event.note, "Новое описание")
        self.assertTrue(event.needs_review)

    def test_removed_row_marked_removed_not_deleted(self):
        self.sync()
        key = source_key(self.source.rows[0])
        del self.source.rows[0]
        report, _run = self.sync()
        self.assertEqual(report.removed, 1)
        event = DowntimeEvent.objects.filter(source_key=key).first()
        self.assertIsNotNone(event)  # НЕ удалён
        self.assertEqual(event.sync_mark, DowntimeEvent.SyncMark.REMOVED)
        self.assertTrue(event.needs_review)
        self.assertEqual(DowntimeEvent.objects.filter(source=DowntimeEvent.Source.SAARC).count(), 3)

    def test_changes_and_removal_are_journaled(self):
        self.sync()
        self.source.rows[0]["ПРИМЕЧАНИЕ"] = "Правка изменилась"
        self.sync()
        event = self.event_by_row(self.source.rows[0])
        self.assertTrue(event.logs.filter(comment__contains="Правка из источника").exists())

        # Снятие тоже пишется в журнал.
        removed_key = source_key(self.source.rows[1])
        del self.source.rows[1]
        self.sync()
        removed = DowntimeEvent.objects.filter(source_key=removed_key).first()
        self.assertTrue(removed.logs.filter(comment__contains="Снято в источнике").exists())

    def test_closed_period_blocks_new_rows(self):
        ReportingPeriod.objects.create(year=2026, month=9)
        report, _run = self.sync()
        self.assertEqual(report.created, 0)
        self.assertEqual(report.skipped_closed, 3)
        self.assertEqual(DowntimeEvent.objects.filter(source=DowntimeEvent.Source.SAARC).count(), 0)

    def test_closed_period_is_not_changed(self):
        self.sync()  # создаём при открытом периоде
        ReportingPeriod.objects.create(year=2026, month=9)
        original_ended = self.event_by_row(self.source.rows[0]).ended_at

        self.source.rows[0]["КОНЕЦ"] = "2026-09-20 10:45:00"
        report, _run = self.sync()
        self.assertEqual(report.skipped_closed, 3)
        self.assertEqual(report.adjusted, 0)
        self.assertEqual(report.review, 0)
        event = self.event_by_row(self.source.rows[0])
        self.assertEqual(event.ended_at, original_ended)
        self.assertFalse(event.needs_review)
        self.assertEqual(event.sync_mark, "")


class SyncViewTests(SyncTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for role in ALL_ROLES:
            Group.objects.get_or_create(name=role)

    def _user(self, username, role=None):
        user = get_user_model().objects.create_user(username=username, password="x")
        if role:
            user.groups.add(Group.objects.get(name=role))
        return user

    def test_sync_page_denied_without_role(self):
        self.client.force_login(self._user("nobody"))
        response = self.client.get("/sync/", **HOST)
        self.assertEqual(response.status_code, 403)

    def test_sync_page_allowed_for_specialist(self):
        self.client.force_login(self._user("sp", role=ROLE_DOWNTIME_SPECIALIST))
        response = self.client.get("/sync/", **HOST)
        self.assertEqual(response.status_code, 200)

    def test_sync_now_creates_and_records_run(self):
        # Кнопка «Забрать сейчас» берёт источник из настроек (мок СААРЦ) и окно
        # за последние дни — поэтому подменяем источник на «свежую» строку.
        start = timezone.now() - timedelta(days=1)
        recent = FakeSource([
            {
                "НАЧАЛО": start.strftime("%Y-%m-%d %H:%M:%S"),
                "КОНЕЦ": (start + timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S"),
                "ПРИМЕЧАНИЕ": "Свежий простой",
                "АГГРЕГАТ": "Площадка №9 окончательной приемки — ОПТ №9",
                "УЧАСТОК": "Участок отделки труб 1020",
                "ФИО": "Иванов И.И.",
                "СЛУЖБА": "ДИТ",
                "ЦЕХ": "ТЭСЦ-4",
            }
        ])
        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        with mock.patch("apps.integrations.services.get_saarc_source", return_value=recent):
            response = self.client.post("/sync/now/", **HOST)
        self.assertEqual(response.status_code, 302)
        run = SyncRun.objects.filter(mode=SyncRun.Mode.MANUAL).get()
        self.assertEqual(run.status, SyncRun.Status.OK)
        self.assertEqual(run.created, 1)
        self.assertEqual(DowntimeEvent.objects.filter(source=DowntimeEvent.Source.SAARC).count(), 1)

    def test_close_period_button(self):
        self.client.force_login(self._user("sp", role=ROLE_DOWNTIME_SPECIALIST))
        response = self.client.post(
            "/sync/close-period/", {"year": "2026", "month": "9"}, **HOST
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ReportingPeriod.objects.filter(year=2026, month=9).exists())

    def test_review_page_and_accept(self):
        self.sync()
        self.source.rows[0]["ПРИМЕЧАНИЕ"] = "Проверить"
        self.sync()
        event = DowntimeEvent.objects.filter(needs_review=True).first()
        self.assertIsNotNone(event)

        self.client.force_login(self._user("itm", role=ROLE_IT_MANAGER))
        response = self.client.get("/sync/review/", **HOST)
        self.assertEqual(response.status_code, 200)

        response = self.client.post(f"/sync/review/{event.pk}/accept/", **HOST)
        self.assertEqual(response.status_code, 302)
        event.refresh_from_db()
        self.assertFalse(event.needs_review)
        # Отметка остаётся — это история записи.
        self.assertEqual(event.sync_mark, DowntimeEvent.SyncMark.CORRECTED)
