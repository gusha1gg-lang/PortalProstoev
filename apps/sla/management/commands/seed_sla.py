"""
Наполнение демонстрационным договором SLA.

Запуск:  python manage.py seed_sla
Требует заполненных справочников (python manage.py seed_catalog).
Идемпотентна: повторный запуск не создаёт дублей.

Создаёт ОБЩИЙ договор (без привязки к цеху) — он действует для всех цехов.
Чтобы задать условия отдельно для конкретного цеха, в админке укажите у договора цех.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.sla.models import SlaContract

TARGET_AVAILABILITY = Decimal("99.50")
PENALTY_PER_HOUR = Decimal("50000.00")


class Command(BaseCommand):
    help = "Создаёт демонстрационный договор SLA (общий — для всех цехов)."

    def handle(self, *args, **options):
        _, was_created = SlaContract.objects.get_or_create(
            workshop=None,
            valid_from="2025-01-01",
            defaults={
                "name": "SLA (все цеха)",
                "target_availability": TARGET_AVAILABILITY,
                "penalty_per_hour": PENALTY_PER_HOUR,
                "note": "Демо-договор",
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Договоры SLA: создано {int(was_created)}. "
                f"Всего договоров: {SlaContract.objects.count()}."
            )
        )
