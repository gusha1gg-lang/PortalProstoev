"""
Периодическая сводка по простоям (ежедневно утром).

Запуск по расписанию (cron):
    python manage.py send_digest
    python manage.py send_digest --date 2026-10-14T08:00

Повторно за тот же день сводка не отправляется (защита в журнале уведомлений).
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.notifications.services import send_digest


class Command(BaseCommand):
    help = "Отправляет периодическую сводку по простоям получателям правил «Сводка»."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="Момент отправки, ГГГГ-ММ-ДДThh:mm (по умолчанию — сейчас)")

    def handle(self, *args, **options):
        moment = None
        if options.get("date"):
            try:
                moment = timezone.make_aware(datetime.fromisoformat(options["date"]))
            except ValueError as exc:
                raise CommandError("Не разобрана дата, нужен формат ГГГГ-ММ-ДДThh:mm") from exc

        logs = send_digest(now=moment)
        if not logs:
            self.stdout.write("Сводка уже отправлена сегодня (или нет активных правил «Сводка»).")
            return
        for log in logs:
            self.stdout.write(f"{log.get_status_display()}: «{log.subject}» → {log.recipients}")
        self.stdout.write(self.style.SUCCESS(f"Сводок отправлено: {len(logs)}"))
