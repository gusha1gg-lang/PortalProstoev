"""
Импорт простоев из источника (СААРЦ) в портал.

Портал не «собирает» простои сам — он фильтрует их из СААРЦ (оставляет только вину ИТ)
и приводит к удобному для ИТ виду.

Запуск:
    python manage.py import_saarc                        # за весь доступный период (мок)
    python manage.py import_saarc --since 2026-09-01 --until 2026-10-01
    python manage.py import_saarc --create-missing       # создавать недостающие участки/агрегаты
    python manage.py import_saarc --update               # обновлять уже загруженные строки

Идемпотентно: повторный запуск не создаёт дублей.
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.services import day_start, import_downtimes
from apps.integrations.saarc import SaarcSourceError


class Command(BaseCommand):
    help = "Импортирует простои из источника СААРЦ (в mock-режиме — из встроенных данных)."

    def add_arguments(self, parser):
        parser.add_argument("--since", help="Начало периода, ГГГГ-ММ-ДД")
        parser.add_argument("--until", help="Конец периода (не включая), ГГГГ-ММ-ДД")
        parser.add_argument(
            "--create-missing",
            action="store_true",
            help="Создавать недостающие участки/агрегаты (цех создавать нельзя — он верхний уровень)",
        )
        parser.add_argument(
            "--update",
            action="store_true",
            help="Обновлять уже загруженные строки (окончание, примечание, ФИО)",
        )
        parser.add_argument(
            "--no-notify",
            dest="notify",
            action="store_false",
            help="Не рассылать уведомления о новых простоях (для массового исторического импорта)",
        )

    def handle(self, *args, **options):
        since = _parse_date(options.get("since"))
        until = _parse_date(options.get("until"))

        try:
            report = import_downtimes(
                since=since,
                until=until,
                create_missing=options["create_missing"],
                update=options["update"],
                notify=options["notify"],
            )
        except SaarcSourceError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(report.as_text())
        self.stdout.write(self.style.SUCCESS("Импорт завершён."))


def _parse_date(text):
    """Разбирает дату ГГГГ-ММ-ДД в начало дня (или None)."""
    if not text:
        return None
    try:
        return day_start(datetime.strptime(text, "%Y-%m-%d").date())
    except ValueError as exc:
        raise CommandError(f"Не разобрана дата «{text}», нужен формат ГГГГ-ММ-ДД") from exc
