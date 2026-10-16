"""
Автосбор простоев из источника (СААРЦ) — запускается по расписанию.

Правила (этап 11.6):
    - только чтение источника, ничего в СААРЦ не меняется;
    - правки/снятие записей НЕ удаляют их, а помечают («Исправлен»/«Скорректирован»/«Снят»)
      и отправляют «на проверку»;
    - закрытые периоды не изменяются.

Запуск по расписанию (например, каждый час):
    0 * * * * cd /path/to/PortalProstoev && ./.venv/bin/python manage.py sync_saarc

Флаги:
    --hours N     окно за последние N часов (по умолчанию 2 — с перекрытием, чтобы ничего не потерять)
    --since       начало периода ГГГГ-ММ-ДД (если задан — заменяет --hours)
    --until       конец периода (не включая) ГГГГ-ММ-ДД
    --create-missing   создавать недостающие участки/агрегаты
    --no-notify   не слать уведомления о новых простоях (для массовой подгрузки)
"""
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.integrations.models import SyncRun
from apps.integrations.saarc import SaarcSourceError
from apps.integrations.services import day_start, sync_downtimes


class Command(BaseCommand):
    help = "Забирает простои из источника СААРЦ (запускать по расписанию, например каждый час)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=2,
            help="Окно за последние N часов (по умолчанию 2 — с небольшим перекрытием)",
        )
        parser.add_argument("--since", help="Начало периода, ГГГГ-ММ-ДД (если задан — заменяет --hours)")
        parser.add_argument("--until", help="Конец периода (не включая), ГГГГ-ММ-ДД")
        parser.add_argument(
            "--create-missing",
            action="store_true",
            help="Создавать недостающие участки/агрегаты (цех создавать нельзя — он верхний уровень)",
        )
        parser.add_argument(
            "--no-notify",
            dest="notify",
            action="store_false",
            help="Не рассылать уведомления о новых простоях",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        if options.get("since") or options.get("until"):
            since = _parse_date(options.get("since")) or (now - timedelta(hours=options["hours"]))
            until = _parse_date(options.get("until")) or now
        else:
            until = now
            since = until - timedelta(hours=options["hours"])

        try:
            report, run = sync_downtimes(
                since=since,
                until=until,
                mode=SyncRun.Mode.AUTO,
                create_missing=options["create_missing"],
                notify=options["notify"],
            )
        except SaarcSourceError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(report.as_text())
        if report.review:
            self.stdout.write(self.style.WARNING(f"На проверку: {report.review}"))
        self.stdout.write(self.style.SUCCESS(f"Синхронизация завершена (запуск #{run.pk})."))


def _parse_date(text):
    """Разбирает дату ГГГГ-ММ-ДД в начало дня (или None)."""
    if not text:
        return None
    try:
        return day_start(datetime.strptime(text, "%Y-%m-%d").date())
    except ValueError as exc:
        raise CommandError(f"Не разобрана дата «{text}», нужен формат ГГГГ-ММ-ДД") from exc
