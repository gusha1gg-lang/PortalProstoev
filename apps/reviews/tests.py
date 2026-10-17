"""Тесты модуля «Разбор простоя» (этап 11.7).

Запуск: ./.venv/bin/python manage.py test apps.reviews
"""
from datetime import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone

from apps.accounts.roles import ROLE_DOWNTIME_SPECIALIST, ROLE_IT_MANAGER, ROLE_OPERATOR
from apps.catalog.models import Workshop
from apps.downtimes.models import DowntimeEvent

from .models import IncidentReview, ReviewLog, TimelineEntry
from .services import (
    add_timeline_entry,
    change_status,
    create_review_from_events,
    delete_timeline_entry,
    eligible_leads,
)

# Тестовый клиент ходит по имени хоста из ALLOWED_HOSTS.
HOST = {"HTTP_HOST": "localhost"}


def dt(text):
    """Дата-время с часовым поясом из строки «ГГГГ-ММ-ДД ЧЧ:ММ»."""
    return timezone.make_aware(datetime.strptime(text, "%Y-%m-%d %H:%M"))


class ReviewTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.workshop = Workshop.objects.create(name="ТЭСЦ-4")
        spec_group, _ = Group.objects.get_or_create(name=ROLE_DOWNTIME_SPECIALIST)
        manager_group, _ = Group.objects.get_or_create(name=ROLE_IT_MANAGER)
        operator_group, _ = Group.objects.get_or_create(name=ROLE_OPERATOR)

        cls.specialist = get_user_model().objects.create_user(username="spec", password="x")
        cls.specialist.groups.add(spec_group)
        cls.manager = get_user_model().objects.create_user(username="man", password="x")
        cls.manager.groups.add(manager_group)
        cls.operator = get_user_model().objects.create_user(username="op", password="x")
        cls.operator.groups.add(operator_group)

    def make_event(self, start, end, note=""):
        return DowntimeEvent.objects.create(
            started_at=dt(start),
            ended_at=dt(end) if end else None,
            workshop=self.workshop,
            note=note,
        )


class ReviewNumberTests(ReviewTestBase):
    def test_number_is_generated(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        review, created = create_review_from_events(
            [event], lead=self.specialist, created_by=self.specialist
        )
        self.assertTrue(created)
        year = timezone.now().year
        self.assertEqual(review.number, f"РП-{year}-0001")

    def test_number_increments(self):
        e1 = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        e2 = self.make_event("2026-10-02 10:00", "2026-10-02 10:30")
        r1, _ = create_review_from_events([e1], lead=self.specialist, created_by=self.specialist)
        r2, _ = create_review_from_events([e2], lead=self.specialist, created_by=self.specialist)
        self.assertEqual(int(r2.number.rsplit("-", 1)[-1]), int(r1.number.rsplit("-", 1)[-1]) + 1)


class CreateReviewServiceTests(ReviewTestBase):
    def test_single_event_creates_case_with_one_event(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30", note="Отказ АРМ")
        review, created = create_review_from_events(
            [event], lead=self.specialist, created_by=self.specialist
        )
        self.assertTrue(created)
        self.assertIsNotNone(review.case_id)
        self.assertEqual(review.events.count(), 1)
        self.assertEqual(review.case.title, "Отказ АРМ")

    def test_several_events_merged_into_one_incident(self):
        e1 = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        e2 = self.make_event("2026-10-01 11:00", "2026-10-01 11:15")
        review, created = create_review_from_events(
            [e1, e2], lead=self.specialist, created_by=self.specialist
        )
        self.assertTrue(created)
        self.assertEqual(review.events.count(), 2)
        # Объединение без двойного счёта: 30 + 15 = 45 минут.
        self.assertEqual(review.case.duration_min, 45)

    def test_existing_case_is_reused(self):
        e1 = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        e2 = self.make_event("2026-10-01 11:00", "2026-10-01 11:15")
        first, _ = create_review_from_events([e1, e2], lead=self.specialist, created_by=self.specialist)

        # Тот же инцидент — новый разбор не плодим.
        again, created = create_review_from_events(
            [e1, e2], lead=self.manager, created_by=self.manager
        )
        self.assertFalse(created)
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(IncidentReview.objects.count(), 1)

    def test_no_events_raises(self):
        with self.assertRaises(ValueError):
            create_review_from_events([], lead=self.specialist, created_by=self.specialist)


class EligibleLeadsTests(ReviewTestBase):
    def test_only_review_roles_are_leads(self):
        leads = set(eligible_leads().values_list("username", flat=True))
        self.assertIn("spec", leads)
        self.assertIn("man", leads)
        self.assertNotIn("op", leads)


class ReviewViewTests(ReviewTestBase):
    def test_anonymous_list_redirects(self):
        response = self.client.get("/reviews/", **HOST)
        self.assertEqual(response.status_code, 302)

    def test_anonymous_detail_redirects(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        review, _ = create_review_from_events(
            [event], lead=self.specialist, created_by=self.specialist
        )
        response = self.client.get(f"/reviews/{review.pk}/", **HOST)
        self.assertEqual(response.status_code, 302)

    def test_any_logged_in_can_view_list(self):
        self.client.force_login(self.operator)
        response = self.client.get("/reviews/", **HOST)
        self.assertEqual(response.status_code, 200)

    def test_operator_cannot_create(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        self.client.force_login(self.operator)
        response = self.client.post(
            "/reviews/new/", {"events": [str(event.pk)]}, **HOST
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(IncidentReview.objects.count(), 0)

    def test_specialist_creates_review(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30", note="Сбой")
        self.client.force_login(self.specialist)
        response = self.client.post(
            "/reviews/new/",
            {"events": [str(event.pk)], "lead": str(self.manager.pk), "title": "Мой разбор"},
            **HOST,
        )
        self.assertEqual(response.status_code, 302)
        review = IncidentReview.objects.get()
        self.assertEqual(review.lead, self.manager)
        self.assertEqual(review.title, "Мой разбор")
        self.assertEqual(response["Location"], f"/reviews/{review.pk}/")

    def test_create_without_events_reports_error(self):
        self.client.force_login(self.specialist)
        response = self.client.post("/reviews/new/", {}, **HOST)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(IncidentReview.objects.count(), 0)

    def test_get_create_redirects_to_list(self):
        self.client.force_login(self.specialist)
        response = self.client.get("/reviews/new/", **HOST)
        self.assertEqual(response.status_code, 302)

    def test_detail_shows_number_and_events(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30", note="Видимая причина")
        review, _ = create_review_from_events(
            [event], lead=self.specialist, created_by=self.specialist
        )
        self.client.force_login(self.specialist)
        response = self.client.get(f"/reviews/{review.pk}/", **HOST)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, review.number)
        self.assertContains(response, "Видимая причина")

    def test_list_filter_by_status(self):
        e1 = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        e2 = self.make_event("2026-10-02 10:00", "2026-10-02 10:30")
        r1, _ = create_review_from_events([e1], lead=self.specialist, created_by=self.specialist)
        r2, _ = create_review_from_events([e2], lead=self.specialist, created_by=self.specialist)
        r2.status = IncidentReview.Status.APPROVED
        r2.save(update_fields=["status"])

        self.client.force_login(self.specialist)
        response = self.client.get("/reviews/?status=approved", **HOST)
        self.assertContains(response, r2.number)
        self.assertNotContains(response, r1.number)


class TimelineServiceTests(ReviewTestBase):
    def make_review(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        review, _ = create_review_from_events(
            [event], lead=self.specialist, created_by=self.specialist
        )
        return review

    def test_add_timeline_entry(self):
        review = self.make_review()
        entry = add_timeline_entry(review, author=self.specialist, text="  Пропала связь  ")
        self.assertEqual(entry.text, "Пропала связь")
        self.assertEqual(entry.author, self.specialist)
        self.assertEqual(review.timeline.count(), 1)
        self.assertIsNotNone(entry.occurred_at)

    def test_add_timeline_entry_with_time(self):
        review = self.make_review()
        moment = dt("2026-10-01 09:00")
        entry = add_timeline_entry(review, author=self.specialist, text="Начало", occurred_at=moment)
        self.assertEqual(entry.occurred_at, moment)

    def test_empty_text_raises(self):
        review = self.make_review()
        with self.assertRaises(ValueError):
            add_timeline_entry(review, author=self.specialist, text="   ")

    def test_delete_timeline_entry(self):
        review = self.make_review()
        entry = add_timeline_entry(review, author=self.specialist, text="Удалить меня")
        delete_timeline_entry(entry, user=self.specialist)
        self.assertEqual(review.timeline.count(), 0)


class StatusServiceTests(ReviewTestBase):
    def make_review(self, status=IncidentReview.Status.DRAFT):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        review, _ = create_review_from_events(
            [event], lead=self.specialist, created_by=self.specialist
        )
        review.status = status
        review.save(update_fields=["status"])
        return review

    def test_valid_transition(self):
        review = self.make_review()
        old, new = change_status(
            review, target=IncidentReview.Status.IN_PROGRESS, user=self.specialist
        )
        self.assertEqual(old, "Черновик")
        self.assertEqual(new, "В работе")
        review.refresh_from_db()
        self.assertEqual(review.status, IncidentReview.Status.IN_PROGRESS)
        self.assertTrue(review.logs.filter(action=ReviewLog.Action.STATUS).exists())

    def test_invalid_transition_raises(self):
        review = self.make_review()
        with self.assertRaises(ValueError):
            change_status(review, target=IncidentReview.Status.APPROVED, user=self.specialist)

    def test_available_transitions(self):
        review = self.make_review()
        targets = [target for target, _ in review.available_transitions()]
        self.assertEqual(targets, [IncidentReview.Status.IN_PROGRESS])

    def test_creation_is_logged(self):
        review = self.make_review()
        self.assertTrue(review.logs.filter(action=ReviewLog.Action.CREATED).exists())


class TimelineViewTests(ReviewTestBase):
    def make_review(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        review, _ = create_review_from_events(
            [event], lead=self.specialist, created_by=self.specialist
        )
        return review

    def test_specialist_adds_timeline_entry(self):
        review = self.make_review()
        self.client.force_login(self.specialist)
        response = self.client.post(
            f"/reviews/{review.pk}/timeline/add/",
            {"text": "Пропала связь", "occurred_at": "2026-10-01T09:30"},
            **HOST,
        )
        self.assertEqual(response.status_code, 302)
        entry = TimelineEntry.objects.get()
        self.assertEqual(entry.text, "Пропала связь")
        self.assertEqual(entry.occurred_at, dt("2026-10-01 09:30"))

    def test_operator_cannot_add_timeline_entry(self):
        review = self.make_review()
        self.client.force_login(self.operator)
        response = self.client.post(
            f"/reviews/{review.pk}/timeline/add/", {"text": "нет прав"}, **HOST
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(TimelineEntry.objects.count(), 0)

    def test_empty_timeline_entry_is_rejected(self):
        review = self.make_review()
        self.client.force_login(self.specialist)
        self.client.post(f"/reviews/{review.pk}/timeline/add/", {"text": "  "}, **HOST)
        self.assertEqual(TimelineEntry.objects.count(), 0)

    def test_delete_timeline_entry_view(self):
        review = self.make_review()
        entry = add_timeline_entry(review, author=self.specialist, text="Удалить")
        self.client.force_login(self.specialist)
        response = self.client.post(
            f"/reviews/{review.pk}/timeline/{entry.pk}/delete/", **HOST
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TimelineEntry.objects.count(), 0)


class StatusViewTests(ReviewTestBase):
    def make_review(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        review, _ = create_review_from_events(
            [event], lead=self.specialist, created_by=self.specialist
        )
        return review

    def test_specialist_changes_status(self):
        review = self.make_review()
        self.client.force_login(self.specialist)
        response = self.client.post(
            f"/reviews/{review.pk}/status/",
            {"to": IncidentReview.Status.IN_PROGRESS},
            **HOST,
        )
        self.assertEqual(response.status_code, 302)
        review.refresh_from_db()
        self.assertEqual(review.status, IncidentReview.Status.IN_PROGRESS)

    def test_invalid_status_change_is_ignored(self):
        review = self.make_review()
        self.client.force_login(self.specialist)
        self.client.post(
            f"/reviews/{review.pk}/status/", {"to": IncidentReview.Status.APPROVED}, **HOST
        )
        review.refresh_from_db()
        self.assertEqual(review.status, IncidentReview.Status.DRAFT)

    def test_operator_cannot_change_status(self):
        review = self.make_review()
        self.client.force_login(self.operator)
        response = self.client.post(
            f"/reviews/{review.pk}/status/",
            {"to": IncidentReview.Status.IN_PROGRESS},
            **HOST,
        )
        self.assertEqual(response.status_code, 403)
