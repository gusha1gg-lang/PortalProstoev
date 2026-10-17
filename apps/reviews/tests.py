"""Тесты модуля «Разбор простоя» (этап 11.7).

Запуск: ./.venv/bin/python manage.py test apps.reviews
"""
from datetime import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from apps.accounts.roles import ROLE_DOWNTIME_SPECIALIST, ROLE_IT_MANAGER, ROLE_OPERATOR
from apps.catalog.models import ItFaultCategory, Workshop
from apps.downtimes.models import DowntimeEvent
from apps.notifications.models import NotificationLog

from .models import (
    ActionTemplate,
    IncidentReview,
    ReviewAction,
    ReviewLog,
    ReviewMessage,
    ReviewParticipant,
    TimelineEntry,
)
from .services import (
    active_templates_for,
    add_participant,
    add_review_action,
    add_timeline_entry,
    change_status,
    create_review_from_events,
    delete_review_action,
    delete_timeline_entry,
    eligible_leads,
    extract_mentions,
    post_review_message,
    remove_participant,
    set_action_status,
    update_review_action,
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

        cls.specialist = get_user_model().objects.create_user(
            username="spec", password="x", email="spec@example.com"
        )
        cls.specialist.groups.add(spec_group)
        cls.manager = get_user_model().objects.create_user(
            username="man", password="x", email="man@example.com"
        )
        cls.manager.groups.add(manager_group)
        cls.operator = get_user_model().objects.create_user(
            username="op", password="x", email="op@example.com"
        )
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


class ParticipantServiceTests(ReviewTestBase):
    def make_review(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        review, _ = create_review_from_events(
            [event], lead=self.specialist, created_by=self.specialist
        )
        return review

    def test_add_participant(self):
        review = self.make_review()
        participant, created = add_participant(review, self.operator, by=self.specialist)
        self.assertTrue(created)
        self.assertEqual(participant.user, self.operator)
        self.assertEqual(review.participants.count(), 1)

    def test_add_participant_twice_is_idempotent(self):
        review = self.make_review()
        add_participant(review, self.operator, by=self.specialist)
        _, created = add_participant(review, self.operator, by=self.specialist)
        self.assertFalse(created)
        self.assertEqual(review.participants.count(), 1)

    def test_remove_participant(self):
        review = self.make_review()
        add_participant(review, self.operator, by=self.specialist)
        remove_participant(review, self.operator, by=self.specialist)
        self.assertEqual(review.participants.count(), 0)


class MentionParsingTests(ReviewTestBase):
    def test_extract_mentions_unique_in_order(self):
        self.assertEqual(
            extract_mentions("Привет @spec и @man, снова @spec!"),
            ["spec", "man"],
        )

    def test_extract_mentions_empty(self):
        self.assertEqual(extract_mentions("без упоминаний"), [])


class ChatServiceTests(ReviewTestBase):
    def make_review(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        review, _ = create_review_from_events(
            [event], lead=self.specialist, created_by=self.specialist
        )
        return review

    def test_post_message_without_mentions(self):
        review = self.make_review()
        message = post_review_message(review, author=self.specialist, text="  Проверяю  ")
        self.assertEqual(message.text, "Проверяю")
        self.assertEqual(review.messages.count(), 1)
        self.assertEqual(message.mentions.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_empty_message_raises(self):
        review = self.make_review()
        with self.assertRaises(ValueError):
            post_review_message(review, author=self.specialist, text="   ")

    def test_mention_adds_participant_and_sends_email(self):
        review = self.make_review()
        message = post_review_message(
            review, author=self.specialist, text="Коллега @man, посмотри, пожалуйста"
        )
        self.assertIn(self.manager, message.mentions.all())
        self.assertTrue(review.participants.filter(user=self.manager).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("man@example.com", mail.outbox[0].to)
        self.assertIn(review.number, mail.outbox[0].body)
        self.assertTrue(
            NotificationLog.objects.filter(event="mention", recipients="man@example.com").exists()
        )

    def test_mention_of_unknown_login_changes_nothing(self):
        review = self.make_review()
        message = post_review_message(review, author=self.specialist, text="Привет @nobody")
        self.assertEqual(message.mentions.count(), 0)
        self.assertEqual(review.participants.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_self_mention_does_not_email(self):
        review = self.make_review()
        post_review_message(review, author=self.specialist, text="Заметка для себя @spec")
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(review.participants.count(), 0)


class ChatViewTests(ReviewTestBase):
    def make_review(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        review, _ = create_review_from_events(
            [event], lead=self.specialist, created_by=self.specialist
        )
        return review

    def test_specialist_posts_message_with_mention(self):
        review = self.make_review()
        self.client.force_login(self.specialist)
        response = self.client.post(
            f"/reviews/{review.pk}/messages/add/",
            {"text": "Работаем, @man"},
            **HOST,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(review.messages.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_participant_can_post_message(self):
        review = self.make_review()
        add_participant(review, self.operator, by=self.specialist)
        self.client.force_login(self.operator)
        response = self.client.post(
            f"/reviews/{review.pk}/messages/add/", {"text": "Я здесь"}, **HOST
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(review.messages.count(), 1)

    def test_outsider_cannot_post_message(self):
        review = self.make_review()
        self.client.force_login(self.operator)
        response = self.client.post(
            f"/reviews/{review.pk}/messages/add/", {"text": "нельзя"}, **HOST
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(review.messages.count(), 0)

    def test_mentioned_user_can_then_view_review(self):
        review = self.make_review()
        post_review_message(review, author=self.specialist, text="Смотри @op")
        self.client.force_login(self.operator)
        response = self.client.get(f"/reviews/{review.pk}/", **HOST)
        self.assertEqual(response.status_code, 200)

    def test_mention_is_highlighted_on_card(self):
        review = self.make_review()
        post_review_message(review, author=self.specialist, text="Зову @man")
        self.client.force_login(self.specialist)
        response = self.client.get(f"/reviews/{review.pk}/", **HOST)
        self.assertContains(response, '<span class="mention">@man</span>', html=False)


class ReviewVisibilityTests(ReviewTestBase):
    def make_review(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        review, _ = create_review_from_events(
            [event], lead=self.specialist, created_by=self.specialist
        )
        return review

    def test_outsider_cannot_open_detail(self):
        review = self.make_review()
        self.client.force_login(self.operator)
        response = self.client.get(f"/reviews/{review.pk}/", **HOST)
        self.assertEqual(response.status_code, 403)

    def test_outsider_list_is_empty(self):
        self.make_review()
        self.client.force_login(self.operator)
        response = self.client.get("/reviews/", **HOST)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.lead_review_number())

    def lead_review_number(self):
        return IncidentReview.objects.get().number

    def test_participant_sees_review_in_list(self):
        review = self.make_review()
        add_participant(review, self.operator, by=self.specialist)
        self.client.force_login(self.operator)
        response = self.client.get("/reviews/", **HOST)
        self.assertContains(response, review.number)


class ParticipantViewTests(ReviewTestBase):
    def make_review(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        review, _ = create_review_from_events(
            [event], lead=self.specialist, created_by=self.specialist
        )
        return review

    def test_specialist_adds_participant(self):
        review = self.make_review()
        self.client.force_login(self.specialist)
        response = self.client.post(
            f"/reviews/{review.pk}/participants/add/",
            {"user": self.operator.pk},
            **HOST,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(review.participants.filter(user=self.operator).exists())

    def test_specialist_removes_participant(self):
        review = self.make_review()
        add_participant(review, self.operator, by=self.specialist)
        self.client.force_login(self.specialist)
        response = self.client.post(
            f"/reviews/{review.pk}/participants/{self.operator.pk}/remove/", **HOST
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(review.participants.count(), 0)

    def test_operator_cannot_add_participant(self):
        review = self.make_review()
        self.client.force_login(self.operator)
        response = self.client.post(
            f"/reviews/{review.pk}/participants/add/",
            {"user": self.operator.pk},
            **HOST,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(review.participants.count(), 0)

    def test_participant_cannot_manage_participants(self):
        review = self.make_review()
        add_participant(review, self.operator, by=self.specialist)
        self.client.force_login(self.operator)
        response = self.client.post(
            f"/reviews/{review.pk}/participants/add/",
            {"user": self.manager.pk},
            **HOST,
        )
        self.assertEqual(response.status_code, 403)


class ActionTemplateServiceTests(ReviewTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.category = ItFaultCategory.objects.create(code="АРМ", name="АРМ")

    def test_active_templates_include_universal_and_matching_category(self):
        universal = ActionTemplate.objects.create(title="Общий")
        matching = ActionTemplate.objects.create(title="АРМ-шаблон", category=self.category)
        other = ItFaultCategory.objects.create(code="БД", name="БД")
        ActionTemplate.objects.create(title="БД-шаблон", category=other)

        titles = [t.title for t in active_templates_for(self.category)]
        self.assertIn("Общий", titles)
        self.assertIn("АРМ-шаблон", titles)
        self.assertNotIn("БД-шаблон", titles)
        self.assertIn(universal, active_templates_for(self.category))
        self.assertIn(matching, active_templates_for(self.category))

    def test_hidden_template_is_not_offered(self):
        ActionTemplate.objects.create(title="Скрытый", is_active=False)
        self.assertNotIn("Скрытый", [t.title for t in active_templates_for(None)])

    def test_ordering_by_order_then_title(self):
        ActionTemplate.objects.create(title="Позже", order=200)
        ActionTemplate.objects.create(title="Раньше", order=10)
        self.assertEqual([t.title for t in active_templates_for(None)], ["Раньше", "Позже"])


class ReviewActionServiceTests(ReviewTestBase):
    def make_review(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        review, _ = create_review_from_events(
            [event], lead=self.specialist, created_by=self.specialist
        )
        return review

    def test_create_action_from_template(self):
        review = self.make_review()
        template = ActionTemplate.objects.create(
            title="Перезагрузить АРМ", description="Проверить питание и перезагрузить"
        )
        action = add_review_action(
            review, created_by=self.specialist, template=template,
            due_at=dt("2026-10-02 09:00"),
        )
        self.assertEqual(action.title, "Перезагрузить АРМ")
        self.assertIn("перезагрузить", action.description)
        self.assertEqual(action.status, ReviewAction.Status.PLANNED)

    def test_explicit_title_beats_template(self):
        review = self.make_review()
        template = ActionTemplate.objects.create(title="Из шаблона")
        action = add_review_action(
            review, created_by=self.specialist, title="Своё название", template=template
        )
        self.assertEqual(action.title, "Своё название")

    def test_create_action_without_title_raises(self):
        review = self.make_review()
        with self.assertRaises(ValueError):
            add_review_action(review, created_by=self.specialist, title="   ")

    def test_assignees_become_participants(self):
        review = self.make_review()
        action = add_review_action(
            review, created_by=self.specialist, title="Задача", assignees=[self.operator]
        )
        self.assertIn(self.operator, action.assignees.all())
        self.assertTrue(review.participants.filter(user=self.operator).exists())

    def test_set_status_changes_and_logs(self):
        review = self.make_review()
        action = add_review_action(review, created_by=self.specialist, title="Задача")
        old, new = set_action_status(action, ReviewAction.Status.DONE, user=self.specialist)
        action.refresh_from_db()
        self.assertEqual(action.status, ReviewAction.Status.DONE)
        self.assertEqual(new, "Выполнено")
        self.assertNotEqual(old, new)
        self.assertTrue(ReviewLog.objects.filter(review=review, comment__contains="Выполнено").exists())

    def test_invalid_status_raises(self):
        review = self.make_review()
        action = add_review_action(review, created_by=self.specialist, title="Задача")
        with self.assertRaises(ValueError):
            set_action_status(action, "nonsense", user=self.specialist)

    def test_update_action_changes_fields_and_assignees(self):
        review = self.make_review()
        action = add_review_action(review, created_by=self.specialist, title="Старое")
        update_review_action(
            action, user=self.specialist, title="Новое", description="детали",
            due_at=dt("2026-10-05 12:00"), assignees=[self.operator],
        )
        action.refresh_from_db()
        self.assertEqual(action.title, "Новое")
        self.assertEqual(action.description, "детали")
        self.assertTrue(action.assignees.filter(pk=self.operator.pk).exists())
        self.assertTrue(review.participants.filter(user=self.operator).exists())

    def test_delete_action_keeps_log(self):
        review = self.make_review()
        action = add_review_action(review, created_by=self.specialist, title="Удалить")
        delete_review_action(action, user=self.specialist)
        self.assertEqual(review.actions.count(), 0)
        self.assertTrue(ReviewLog.objects.filter(review=review, comment__contains="Удалено").exists())


class ReviewActionViewTests(ReviewTestBase):
    def make_review(self):
        event = self.make_event("2026-10-01 10:00", "2026-10-01 10:30")
        review, _ = create_review_from_events(
            [event], lead=self.specialist, created_by=self.specialist
        )
        return review

    def test_specialist_adds_action(self):
        review = self.make_review()
        self.client.force_login(self.specialist)
        response = self.client.post(
            f"/reviews/{review.pk}/actions/add/",
            {"title": "Проверить АРМ", "due_at": "2026-10-02T09:00", "assignees": [self.operator.pk]},
            **HOST,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(review.actions.count(), 1)
        self.assertTrue(review.participants.filter(user=self.operator).exists())

    def test_action_from_template_via_view(self):
        review = self.make_review()
        template = ActionTemplate.objects.create(title="Из шаблона", description="шаг 1")
        self.client.force_login(self.specialist)
        self.client.post(
            f"/reviews/{review.pk}/actions/add/", {"template": template.pk}, **HOST
        )
        action = review.actions.get()
        self.assertEqual(action.title, "Из шаблона")
        self.assertEqual(action.description, "шаг 1")

    def test_outsider_cannot_add_action(self):
        review = self.make_review()
        self.client.force_login(self.operator)
        response = self.client.post(
            f"/reviews/{review.pk}/actions/add/", {"title": "нельзя"}, **HOST
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(review.actions.count(), 0)

    def test_specialist_changes_action_status(self):
        review = self.make_review()
        action = add_review_action(review, created_by=self.specialist, title="Задача")
        self.client.force_login(self.specialist)
        response = self.client.post(
            f"/reviews/{review.pk}/actions/{action.pk}/status/",
            {"to": ReviewAction.Status.IN_PROGRESS},
            **HOST,
        )
        self.assertEqual(response.status_code, 302)
        action.refresh_from_db()
        self.assertEqual(action.status, ReviewAction.Status.IN_PROGRESS)

    def test_outsider_cannot_change_action_status(self):
        review = self.make_review()
        action = add_review_action(review, created_by=self.specialist, title="Задача")
        self.client.force_login(self.operator)
        response = self.client.post(
            f"/reviews/{review.pk}/actions/{action.pk}/status/",
            {"to": ReviewAction.Status.DONE},
            **HOST,
        )
        self.assertEqual(response.status_code, 403)

    def test_specialist_edits_action(self):
        review = self.make_review()
        action = add_review_action(review, created_by=self.specialist, title="Старое")
        self.client.force_login(self.specialist)
        response = self.client.post(
            f"/reviews/{review.pk}/actions/{action.pk}/edit/",
            {"title": "Новое", "description": "", "due_at": ""},
            **HOST,
        )
        self.assertEqual(response.status_code, 302)
        action.refresh_from_db()
        self.assertEqual(action.title, "Новое")

    def test_edit_form_opens(self):
        review = self.make_review()
        action = add_review_action(review, created_by=self.specialist, title="Старое")
        self.client.force_login(self.specialist)
        response = self.client.get(
            f"/reviews/{review.pk}/actions/{action.pk}/edit/", **HOST
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Старое")

    def test_participant_cannot_delete_action(self):
        review = self.make_review()
        action = add_review_action(review, created_by=self.specialist, title="Задача")
        add_participant(review, self.operator, by=self.specialist)
        self.client.force_login(self.operator)
        response = self.client.post(
            f"/reviews/{review.pk}/actions/{action.pk}/delete/", **HOST
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(review.actions.count(), 1)

    def test_specialist_deletes_action(self):
        review = self.make_review()
        action = add_review_action(review, created_by=self.specialist, title="Задача")
        self.client.force_login(self.specialist)
        response = self.client.post(
            f"/reviews/{review.pk}/actions/{action.pk}/delete/", **HOST
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(review.actions.count(), 0)

    def test_card_shows_overdue_mark(self):
        review = self.make_review()
        add_review_action(
            review, created_by=self.specialist, title="Просроченная",
            due_at=dt("2020-01-01 00:00"),
        )
        self.client.force_login(self.specialist)
        response = self.client.get(f"/reviews/{review.pk}/", **HOST)
        self.assertContains(response, "просрочено")


class TemplateViewTests(ReviewTestBase):
    def test_specialist_sees_templates_page(self):
        ActionTemplate.objects.create(title="Общий")
        self.client.force_login(self.specialist)
        response = self.client.get("/reviews/templates/", **HOST)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Общий")

    def test_operator_cannot_open_templates(self):
        self.client.force_login(self.operator)
        response = self.client.get("/reviews/templates/", **HOST)
        self.assertEqual(response.status_code, 403)

    def test_specialist_adds_template(self):
        self.client.force_login(self.specialist)
        response = self.client.post(
            "/reviews/templates/add/",
            {"title": "Перезагрузить АРМ", "description": "по питанию", "order": "10"},
            **HOST,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ActionTemplate.objects.filter(title="Перезагрузить АРМ").exists())

    def test_add_template_without_title_is_rejected(self):
        self.client.force_login(self.specialist)
        self.client.post("/reviews/templates/add/", {"title": "  "}, **HOST)
        self.assertEqual(ActionTemplate.objects.count(), 0)

    def test_specialist_toggles_template(self):
        template = ActionTemplate.objects.create(title="Общий")
        self.client.force_login(self.specialist)
        self.client.post(f"/reviews/templates/{template.pk}/toggle/", **HOST)
        template.refresh_from_db()
        self.assertFalse(template.is_active)
        self.client.post(f"/reviews/templates/{template.pk}/toggle/", **HOST)
        template.refresh_from_db()
        self.assertTrue(template.is_active)

    def test_specialist_edits_template(self):
        template = ActionTemplate.objects.create(title="Старое")
        self.client.force_login(self.specialist)
        response = self.client.post(
            f"/reviews/templates/{template.pk}/edit/",
            {"title": "Новое", "description": "детали", "order": "5"},
            **HOST,
        )
        self.assertEqual(response.status_code, 302)
        template.refresh_from_db()
        self.assertEqual(template.title, "Новое")
        self.assertEqual(template.order, 5)
