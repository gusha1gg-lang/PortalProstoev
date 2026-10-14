"""
Наполнение демонстрационными договорами SLA.

Запуск:  python manage.py seed_sla
Требует заполненных справочников (python manage.py seed_catalog).
Идемпотентна: повторный запуск не создаёт дублей.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.catalog.models import Enterprise
from apps.sla.models import SlaContract

TARGET_AVAILABILITY = Decimal("99.50")
PENALTY_PER_HOUR = Decimal("50000.00")


class Command(BaseCommand):
    help = "Создаёт демонстрационные договоры SLA для всех предприятий."

    def handle(self, *args, **options):
        created = 0
        for enterprise in Enterprise.objects.all():
            _, was_created = SlaContract.objects.get_or_create(
                enterprise=enterprise,
                valid_from="2025-01-01",
                defaults={
                    "name": f"SLA {enterprise.name}",
                    "target_availability": TARGET_AVAILABILITY,
                    "penalty_per_hour": PENALTY_PER_HOUR,
                    "note": "Демо-договор",
                },
            )
            created += int(was_created)

        self.stdout.write(
            self.style.SUCCESS(
                f"Договоры SLA: создано {created}. Всего договоров: {SlaContract.objects.count()}."
            )
        )
