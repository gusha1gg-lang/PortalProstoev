"""Тесты уведомлений (запуск: python manage.py test apps.notifications)."""
from datetime import datetime
from decimal import Decimal

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Enterprise, LossRate, Section, Workshop
from apps.downtimes.models import DowntimeEvent
from apps.downtimes.services import save_with_audit
from apps.sla.models import SlaContract

from .models import NotificationLog, NotificationRecipient, NotificationRule
from .services import (
    check_escalations,
    notify_new_incident,
    rules_for,
    send_digest,
    send_rule,
    send_test,
)


def dt(text):
    """Дата-время с часовым поясом из строки «ГГГГ-ММ-ДД ЧЧ:ММ»."""
    return timezone.make_aware(datetime.strptime(text, "%Y-%m-%d %H:%M"))


def make_rule(event, enterprise=None, threshold=80, email="user@example.local"):
    """Создаёт правило с одним получателем и возвращает его."""
    rule = NotificationRule.objects.create(
        name=f"Правило {event}", event=event, enterprise=enterprise, threshold_percent=threshold
    )
    NotificationRecipient.objects.create(rule=rule, email=email)
    return rule


class NotificationTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.enterprise = Enterprise.objects.create(name="Тестовый завод")
        cls.workshop = Workshop.objects.create(enterprise=cls.enterprise, name="ТЭСЦ-4")
        cls.section = Section.objects.create(workshop=cls.workshop, name="Участок отделки")
        LossRate.objects.create(
            section=cls.section,
            cost_per_hour=Decimal("120000"),
            ton_margin=Decimal("0"),
            valid_from="2025-01-01",
        )

    def make_event(self, start, end):
        event = DowntimeEvent(
            started_at=dt(start),
            ended_at=dt(end),
            workshop=self.workshop,
            section=self.section,
            status=DowntimeEvent.Status.CONFIRMED,
            fault_side=DowntimeEvent.FaultSide.IT,
            note="Тестовый простой",
        )
        save_with_audit(event, user=None)
        return event


class SendRuleTests(NotificationTestBase):
    def test_send_writes_log_and_email(self):
        rule = make_rule(NotificationRule.Event.DIGEST)
        log = send_rule(rule, "key-1", {"period": "2026-10", "incident_count": 0, "downtime_hours": 0,
                                        "loss": 0, "availability": 100, "penalty": 0})
        self.assertIsNotNone(log)
        self.assertEqual(log.status, NotificationLog.Status.SENT)
        self.assertEqual(NotificationLog.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_same_key_is_not_sent_twice(self):
        rule = make_rule(NotificationRule.Event.DIGEST)
        first = send_rule(rule, "same-key", {"period": "2026-10"})
        second = send_rule(rule, "same-key", {"period": "2026-10"})
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(mail.outbox), 1)

    def test_rule_without_recipients_sends_nothing(self):
        rule = NotificationRule.objects.create(name="Пустое", event=NotificationRule.Event.DIGEST)
        self.assertIsNone(send_rule(rule, "no-recipients", {"period": "2026-10"}))
        self.assertEqual(len(mail.outbox), 0)

    def test_send_test_uses_email_channel(self):
        self.assertEqual(send_test("me@example.local"), "sent")
        self.assertEqual(len(mail.outbox), 1)


class RuleSelectionTests(NotificationTestBase):
    def test_enterprise_scope(self):
        rule_all = make_rule(NotificationRule.Event.NEW_INCIDENT)
        rule_one = make_rule(NotificationRule.Event.NEW_INCIDENT, enterprise=self.enterprise)
        other = Enterprise.objects.create(name="Другой завод")

        for_enterprise = {r.pk for r in rules_for(NotificationRule.Event.NEW_INCIDENT, self.enterprise)}
        for_other = {r.pk for r in rules_for(NotificationRule.Event.NEW_INCIDENT, other)}

        self.assertEqual(for_enterprise, {rule_all.pk, rule_one.pk})
        self.assertEqual(for_other, {rule_all.pk})


class NewIncidentTests(NotificationTestBase):
    def test_new_incident_notifies(self):
        make_rule(NotificationRule.Event.NEW_INCIDENT)
        event = self.make_event("2026-10-10 15:00", "2026-10-10 15:30")
        logs = notify_new_incident(event)
        self.assertEqual(len(logs), 1)
        self.assertIn("Новый простой", mail.outbox[0].subject)


class EscalationTests(NotificationTestBase):
    def _contract(self, target, penalty="50000"):
        SlaContract.objects.create(
            enterprise=self.enterprise,
            name="Договор",
            target_availability=Decimal(target),
            penalty_per_hour=Decimal(penalty),
            valid_from="2025-01-01",
        )

    def test_breach_is_reported_when_limit_exceeded(self):
        # Почти 100% доступность → допустимы считанные минуты, 30 минут = превышение.
        self._contract("99.99")
        make_rule(NotificationRule.Event.SLA_BREACH)
        self.make_event("2026-10-10 15:00", "2026-10-10 15:30")

        logs = check_escalations(now=dt("2026-10-15 09:00"))
        self.assertEqual(len(logs), 1)
        self.assertIn("Превышение", mail.outbox[0].subject)

    def test_warning_at_threshold(self):
        # Доступность 99,50% → лимит ≈ 223 мин за октябрь; 200 минут ≈ 90% (>= 80%).
        self._contract("99.50")
        make_rule(NotificationRule.Event.SLA_WARNING, threshold=80)
        self.make_event("2026-10-10 12:00", "2026-10-10 15:20")  # 200 минут

        logs = check_escalations(now=dt("2026-10-15 09:00"))
        self.assertEqual(len(logs), 1)
        self.assertIn("Предупреждение", mail.outbox[0].subject)

    def test_no_notification_when_below_threshold(self):
        self._contract("99.50")
        make_rule(NotificationRule.Event.SLA_WARNING, threshold=80)
        self.make_event("2026-10-10 15:00", "2026-10-10 15:30")  # 30 минут — мало

        logs = check_escalations(now=dt("2026-10-15 09:00"))
        self.assertEqual(logs, [])
        self.assertEqual(len(mail.outbox), 0)

    def test_second_check_does_not_repeat(self):
        self._contract("99.99")
        make_rule(NotificationRule.Event.SLA_BREACH)
        self.make_event("2026-10-10 15:00", "2026-10-10 15:30")

        check_escalations(now=dt("2026-10-15 09:00"))
        again = check_escalations(now=dt("2026-10-15 09:10"))
        self.assertEqual(again, [])
        self.assertEqual(len(mail.outbox), 1)


class DigestAndCommandsTests(NotificationTestBase):
    def test_digest_sends_once_per_day(self):
        make_rule(NotificationRule.Event.DIGEST)
        self.make_event("2026-10-10 15:00", "2026-10-10 15:30")

        first = send_digest(now=dt("2026-10-14 08:00"))
        second = send_digest(now=dt("2026-10-14 09:00"))
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(len(mail.outbox), 1)

    def test_check_escalations_command_runs(self):
        self._contract_helper()
        make_rule(NotificationRule.Event.SLA_BREACH)
        self.make_event("2026-10-10 15:00", "2026-10-10 15:30")
        call_command("check_escalations", "--date", "2026-10-15T09:00")
        self.assertEqual(len(mail.outbox), 1)

    def test_digest_and_test_commands_run(self):
        make_rule(NotificationRule.Event.DIGEST)
        call_command("send_digest", "--date", "2026-10-14T08:00")
        call_command("notify_test", "--to", "me@example.local")
        self.assertEqual(len(mail.outbox), 2)

    def _contract_helper(self):
        SlaContract.objects.create(
            enterprise=self.enterprise,
            name="Договор",
            target_availability=Decimal("99.99"),
            penalty_per_hour=Decimal("50000"),
            valid_from="2025-01-01",
        )
