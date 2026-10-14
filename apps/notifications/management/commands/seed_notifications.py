"""
Демонстрационные правила уведомлений (для разработки).

    python manage.py seed_notifications

Создаёт четыре правила (все события) и получателей-заглушки. На проде адреса
получателей поменяются на рабочие (см. question.md, В22–В24).
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.notifications.models import NotificationRecipient, NotificationRule

RULES = [
    {
        "name": "Новый инцидент — ИТ-служба",
        "event": NotificationRule.Event.NEW_INCIDENT,
        "recipients": [("it-service@example.local", "ИТ-служба")],
    },
    {
        "name": "Предупреждение SLA (80%)",
        "event": NotificationRule.Event.SLA_WARNING,
        "threshold_percent": 80,
        "recipients": [("manager@example.local", "Руководитель")],
    },
    {
        "name": "Эскалация SLA — превышение лимита",
        "event": NotificationRule.Event.SLA_BREACH,
        "recipients": [
            ("manager@example.local", "Руководитель"),
            ("it-service@example.local", "ИТ-служба"),
        ],
    },
    {
        "name": "Ежедневная сводка",
        "event": NotificationRule.Event.DIGEST,
        "recipients": [("manager@example.local", "Руководитель")],
    },
]


class Command(BaseCommand):
    help = "Создаёт демонстрационные правила уведомлений и получателей."

    @transaction.atomic
    def handle(self, *args, **options):
        created_rules, created_recipients = 0, 0
        for item in RULES:
            rule, created = NotificationRule.objects.get_or_create(
                name=item["name"],
                defaults={
                    "event": item["event"],
                    "threshold_percent": item.get("threshold_percent", 80),
                },
            )
            if created:
                created_rules += 1
            for email, name in item["recipients"]:
                _, recipient_created = NotificationRecipient.objects.get_or_create(
                    rule=rule, email=email, defaults={"name": name}
                )
                if recipient_created:
                    created_recipients += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Правил создано: {created_rules}, получателей: {created_recipients}."
            )
        )
