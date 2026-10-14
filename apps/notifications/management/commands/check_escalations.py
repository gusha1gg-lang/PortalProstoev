"""
Проверка лимитов SLA и рассылка предупреждений/эскалаций.

Запуск по расписанию (cron), например каждые 10 минут:
    python manage.py check_escalations
    python manage.py check_escalations --date 2026-10-01T09:00

Одно и то же письмо повторно не отправляется (защита в журнале уведомлений).
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.notifications.services import check_escalations


class Command(BaseCommand):
    help = "Проверяет лимиты SLA и рассылает предупреждения/эскалации по email."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            help="Момент проверки, ГГГГ-ММ-ДДThh:mm (по умолчанию — сейчас)",
        )

    def handle(self, *args, **options):
        moment = None
        if options.get("date"):
            try:
                moment = timezone.make_aware(datetime.fromisoformat(options["date"]))
            except ValueError as exc:
                raise CommandError("Не разобрана дата, нужен формат ГГГГ-ММ-ДДThh:mm") from exc

        logs = check_escalations(now=moment)
        if not logs:
            self.stdout.write("Новых предупреждений и эскалаций нет.")
            return
        for log in logs:
            self.stdout.write(f"{log.get_status_display()}: «{log.subject}» → {log.recipients}")
        self.stdout.write(self.style.SUCCESS(f"Отправлено уведомлений: {len(logs)}"))
