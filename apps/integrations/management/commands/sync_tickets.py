"""
Синхронизация статусов уже привязанных тикетов OMNITRACKER.

Запуск:  python manage.py sync_tickets

Новые связи автоматически не создаются — правило «какой тикет к какому инциденту»
ещё согласуется (см. question.md, В16). Команда обновляет тему/статус/ссылку у связей,
которые уже заведены (вручную в админке или программно).
"""
from django.core.management.base import BaseCommand, CommandError

from apps.integrations.omnitracker import OmniTrackerError
from apps.integrations.services import fetch_tickets, sync_tickets


class Command(BaseCommand):
    help = "Синхронизирует статусы тикетов OMNITRACKER для уже созданных связей."

    def add_arguments(self, parser):
        parser.add_argument(
            "--list",
            action="store_true",
            help="Просто показать доступные тикеты (без изменения связей)",
        )

    def handle(self, *args, **options):
        try:
            if options["list"]:
                tickets = fetch_tickets()
                self.stdout.write(f"Доступно тикетов: {len(tickets)}")
                for ticket in tickets:
                    self.stdout.write(f"  {ticket.external_id} · {ticket.status} · {ticket.title}")
                return

            summary = sync_tickets()
        except OmniTrackerError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            f"Тикетов доступно: {summary['tickets']}, связей обновлено: {summary['updated']}, "
            f"связей всего: {summary['linked']}."
        )
        if summary["unlinked"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Тикетов без связи: {summary['unlinked']} — правила связывания ждут согласования (В16)."
                )
            )
