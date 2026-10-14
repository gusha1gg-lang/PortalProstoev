"""Тесты модуля «Простои» (запуск: python manage.py test apps.downtimes)."""
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Enterprise, ItFaultCategory, Section, Workshop

from .models import DowntimeCase, DowntimeCaseLog, DowntimeEvent, DowntimeEventLog
from .services import (
    attach_events,
    create_case_from_events,
    detach_event,
    find_duplicate_candidates,
    recalc_case,
    save_with_audit,
    union_duration_min,
)


def dt(text):
    """Дата-время с часовым поясом из строки «ГГГГ-ММ-ДД ЧЧ:ММ»."""
    return timezone.make_aware(datetime.strptime(text, "%Y-%m-%d %H:%M"))


class UnionDurationTests(TestCase):
    """Расчёт длительности объединением интервалов (без двойного счёта)."""

    def test_empty_returns_zero(self):
        self.assertEqual(union_duration_min([]), 0)

    def test_single_interval(self):
        self.assertEqual(union_duration_min([(dt("2026-10-01 10:00"), dt("2026-10-01 10:30"))]), 30)

    def test_disjoint_intervals_add_up(self):
        result = union_duration_min([
            (dt("2026-10-01 10:00"), dt("2026-10-01 10:30")),
            (dt("2026-10-01 11:00"), dt("2026-10-01 11:15")),
        ])
        self.assertEqual(result, 45)

    def test_overlapping_counts_once(self):
        result = union_duration_min([
            (dt("2026-10-01 10:00"), dt("2026-10-01 10:30")),
            (dt("2026-10-01 10:15"), dt("2026-10-01 10:45")),
        ])
        self.assertEqual(result, 45)

    def test_touching_intervals_merge(self):
        result = union_duration_min([
            (dt("2026-10-01 10:00"), dt("2026-10-01 10:30")),
            (dt("2026-10-01 10:30"), dt("2026-10-01 11:00")),
        ])
        self.assertEqual(result, 60)

    def test_nested_interval_does_not_double_count(self):
        result = union_duration_min([
            (dt("2026-10-01 10:00"), dt("2026-10-01 11:00")),
            (dt("2026-10-01 10:10"), dt("2026-10-01 10:20")),
        ])
        self.assertEqual(result, 60)

    def test_unsorted_input_is_handled(self):
        result = union_duration_min([
            (dt("2026-10-01 11:00"), dt("2026-10-01 11:15")),
            (dt("2026-10-01 10:00"), dt("2026-10-01 10:30")),
        ])
        self.assertEqual(result, 45)

    def test_open_interval_is_ignored(self):
        # Ещё идущий простой (нет окончания) в расчёт длительности не берём.
        result = union_duration_min([
            (dt("2026-10-01 10:00"), dt("2026-10-01 10:30")),
            (dt("2026-10-01 12:00"), None),
        ])
        self.assertEqual(result, 30)


class DowntimeTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.enterprise = Enterprise.objects.create(name="Тестовый завод")
        cls.workshop = Workshop.objects.create(enterprise=cls.enterprise, name="ТЭСЦ-4")
        cls.section = Section.objects.create(workshop=cls.workshop, name="Участок отделки")
        cls.category = ItFaultCategory.objects.create(code="net", name="Сеть")
        cls.user = get_user_model().objects.create_user(username="tester", password="x")

    def make_event(self, start, end, note="", category=None, workshop=None):
        event = DowntimeEvent(
            started_at=dt(start),
            ended_at=dt(end) if end else None,
            workshop=workshop or self.workshop,
            section=self.section,
            fault_side=DowntimeEvent.FaultSide.IT,
            fault_category=category,
            note=note,
        )
        save_with_audit(event, user=self.user)
        return event


class EventSaveTests(DowntimeTestBase):
    def test_duration_is_recomputed_on_save(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:45")
        self.assertEqual(event.duration_min, 45)

    def test_open_event_has_zero_duration(self):
        event = self.make_event("2026-10-01 10:00", None)
        self.assertEqual(event.duration_min, 0)

    def test_empty_external_id_becomes_none(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:10")
        self.assertIsNone(event.external_id)

    def test_duplicate_external_id_is_rejected(self):
        self.make_event("2026-10-01 10:00", "2026-10-01 10:10")
        DowntimeEvent.objects.filter(pk__isnull=False).update(external_id="same", source=DowntimeEvent.Source.SAARC)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DowntimeEvent.objects.create(
                started_at=dt("2026-10-01 11:00"),
                ended_at=dt("2026-10-01 11:10"),
                workshop=self.workshop,
                external_id="same",
                source=DowntimeEvent.Source.SAARC,
            )

    def test_ended_before_started_is_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            DowntimeEvent.objects.create(
                started_at=dt("2026-10-01 11:00"),
                ended_at=dt("2026-10-01 10:00"),
                workshop=self.workshop,
            )

    def test_str_contains_workshop_and_duration(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        self.assertIn("ТЭСЦ-4", str(event))
        self.assertIn("30 мин", str(event))


class AuditTests(DowntimeTestBase):
    def test_create_writes_created_log(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        log = event.logs.get()
        self.assertEqual(log.action, DowntimeEventLog.Action.CREATED)
        self.assertEqual(log.user, self.user)

    def test_update_writes_changes(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        event.note = "Уточнили причину"
        save_with_audit(event, user=self.user)
        log = event.logs.order_by("-created_at").first()
        self.assertEqual(log.action, DowntimeEventLog.Action.UPDATED)
        self.assertIn("Примечание", log.changes)

    def test_status_change_is_marked_as_status(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        event.status = DowntimeEvent.Status.CONFIRMED
        save_with_audit(event, user=self.user)
        log = event.logs.order_by("-created_at").first()
        self.assertEqual(log.action, DowntimeEventLog.Action.STATUS)
        self.assertIn("Статус", log.changes)

    def test_save_without_changes_writes_no_log(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        save_with_audit(event, user=self.user)  # без изменений
        self.assertEqual(event.logs.count(), 1)  # только «Создание»


class CaseMergeTests(DowntimeTestBase):
    def test_create_case_from_events_builds_title_and_duration(self):
        e1 = self.make_event("2026-10-01 10:00", "2026-10-01 10:30", note="Отказ сервера", category=self.category)
        e2 = self.make_event("2026-10-01 10:15", "2026-10-01 10:45", note="Отказ сервера")
        case = create_case_from_events([e1, e2], user=self.user)

        self.assertEqual(case.title, "Отказ сервера")
        self.assertEqual(case.duration_min, 45)  # объединение, без двойного счёта
        self.assertEqual(case.fault_category, self.category)
        self.assertEqual(case.events.count(), 2)
        e1.refresh_from_db()
        self.assertEqual(e1.case, case)

    def test_create_case_requires_events(self):
        with self.assertRaises(ValueError):
            create_case_from_events([], user=self.user)

    def test_case_number_has_expected_format(self):
        e1 = self.make_event("2026-10-01 10:00", "2026-10-01 10:10")
        case = create_case_from_events([e1], user=self.user)
        self.assertRegex(case.number, r"^К-\d{4}-\d{4}$")

    def test_attach_logs_merge(self):
        e1 = self.make_event("2026-10-01 10:00", "2026-10-01 10:10")
        case = create_case_from_events([e1], user=self.user)
        actions = set(case.logs.values_list("action", flat=True))
        self.assertIn(DowntimeCaseLog.Action.MERGED, actions)

    def test_detach_recalculates_and_logs(self):
        e1 = self.make_event("2026-10-01 10:00", "2026-10-01 10:30", note="X")
        e2 = self.make_event("2026-10-01 11:00", "2026-10-01 11:15", note="X")
        case = create_case_from_events([e1, e2], user=self.user)
        self.assertEqual(case.duration_min, 45)

        detach_event(e2, user=self.user)

        case.refresh_from_db()
        e2.refresh_from_db()
        self.assertIsNone(e2.case)
        self.assertEqual(case.duration_min, 30)
        self.assertIn(
            DowntimeCaseLog.Action.UNMERGED, set(case.logs.values_list("action", flat=True))
        )

    def test_detach_without_case_returns_none(self):
        e1 = self.make_event("2026-10-01 10:00", "2026-10-01 10:10")
        self.assertIsNone(detach_event(e1, user=self.user))

    def test_open_event_keeps_case_open(self):
        e1 = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        e2 = self.make_event("2026-10-01 11:00", None)  # ещё идёт
        case = create_case_from_events([e1, e2], user=self.user)
        self.assertIsNone(case.ended_at)

    def test_recalc_case_without_events(self):
        case = DowntimeCase.objects.create(title="Пустой")
        recalc_case(case)
        self.assertEqual(case.duration_min, 0)
        self.assertIsNone(case.started_at)


class DuplicateCandidateTests(DowntimeTestBase):
    def test_same_note_within_window_is_a_group(self):
        self.make_event("2026-10-01 10:00", "2026-10-01 10:10", note="ДМАП")
        self.make_event("2026-10-01 10:30", "2026-10-01 10:40", note="ДМАП")
        groups = find_duplicate_candidates()
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)

    def test_outside_window_is_not_a_group(self):
        self.make_event("2026-10-01 10:00", "2026-10-01 10:10", note="ДМАП")
        self.make_event("2026-10-01 14:00", "2026-10-01 14:10", note="ДМАП")  # +4 часа
        self.assertEqual(find_duplicate_candidates(), [])

    def test_different_enterprise_is_not_a_group(self):
        other = Enterprise.objects.create(name="Другой завод")
        other_workshop = Workshop.objects.create(enterprise=other, name="Цех-1")
        self.make_event("2026-10-01 10:00", "2026-10-01 10:10", note="ДМАП")
        self.make_event("2026-10-01 10:30", "2026-10-01 10:40", note="ДМАП", workshop=other_workshop)
        self.assertEqual(find_duplicate_candidates(), [])

    def test_blank_note_is_ignored(self):
        self.make_event("2026-10-01 10:00", "2026-10-01 10:10", note="")
        self.make_event("2026-10-01 10:30", "2026-10-01 10:40", note="")
        self.assertEqual(find_duplicate_candidates(), [])

    def test_event_in_case_is_not_a_candidate(self):
        e1 = self.make_event("2026-10-01 10:00", "2026-10-01 10:10", note="ДМАП")
        self.make_event("2026-10-01 10:30", "2026-10-01 10:40", note="ДМАП")
        create_case_from_events([e1], user=self.user)  # первый уже в кейсе
        self.assertEqual(find_duplicate_candidates(), [])

    def test_matching_is_case_insensitive(self):
        self.make_event("2026-10-01 10:00", "2026-10-01 10:10", note="ДМАП")
        self.make_event("2026-10-01 10:30", "2026-10-01 10:40", note="дмап")
        self.assertEqual(len(find_duplicate_candidates()), 1)
