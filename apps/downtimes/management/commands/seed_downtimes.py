"""
Наполнение демонстрационными простоями (по данным выгрузки Excel).

Запуск:  python manage.py seed_downtimes
Требует заполненных справочников (python manage.py seed_catalog).
Идемпотентна: опознаёт записи по внешнему ID (source=Файл).

Сценарий «система ДМАП» повторяет реальную картину: один сбой записан несколько раз
по разным агрегатам и людям. Это нужно, чтобы на этапе 4 показать объединение в один кейс.
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.catalog.models import ItFaultCategory, ItFaultSubcategory, Section, Unit, Workshop
from apps.downtimes.models import DowntimeEvent
from apps.downtimes.services import save_with_audit

ENTERPRISE = 'АО "ВМЗ"'
WORKSHOP = "ТЭСЦ-4"

# (внешний ID, начало, конец, участок, агрегат, примечание, ФИО, категория, подкатегория, статус, вина)
DEMO_EVENTS = [
    (
        "demo-001", "2026-10-10 15:01", "2026-10-10 15:24",
        "Участок ремонта и гидроиспытаний 1020", "Участок гидропресса №2 — П9046-2",
        "Не работает система ДМАП", "Кондрушин А.М.",
        "APP", "APP-CR", DowntimeEvent.Status.CLOSED, DowntimeEvent.FaultSide.IT,
    ),
    (
        "demo-002", "2026-10-10 15:05", "2026-10-10 15:20",
        "Участок отделки труб 1020", "Площадка №9 окончательной приемки — ОПТ №9",
        "Не работает система ДМАП", "Орлов С.В.",
        "APP", "APP-CR", DowntimeEvent.Status.CONFIRMED, DowntimeEvent.FaultSide.IT,
    ),
    (
        "demo-003", "2026-10-10 15:05", "2026-10-10 15:20",
        "Участок отделки труб 1020", "Участок АУЗК-31 — АУЗК-31",
        "Не работает система ДМАП", "Аникин Д.Н.",
        "APP", "APP-CR", DowntimeEvent.Status.CONFIRMED, DowntimeEvent.FaultSide.IT,
    ),
    (
        "demo-004", "2026-10-10 15:09", "2026-10-10 15:11",
        "Участок сварки труб 1020", "Ремонтная площадка №3 — ССС-3",
        "Не работает система ДМАП", "Орлов С.В.",
        "APP", "APP-CR", DowntimeEvent.Status.CONFIRMED, DowntimeEvent.FaultSide.IT,
    ),
    (
        "demo-005", "2026-10-10 15:10", "2026-10-10 15:12",
        "Участок формовки труб 1020", "Участок клеймовки и накопителя — Участок клеймения труб",
        "Не работает система ДМАП", "Аникин Д.Н.",
        "APP", "APP-CR", DowntimeEvent.Status.CONFIRMED, DowntimeEvent.FaultSide.IT,
    ),
    (
        "demo-006", "2026-10-11 09:15", "2026-10-11 09:45",
        "Участок ремонта и гидроиспытаний 1020", "Участок гидропресса №2 — П9046-2",
        "Отключение электроэнергии (не наша вина)", "Сидоров П.П.",
        None, None, DowntimeEvent.Status.CANCELED, DowntimeEvent.FaultSide.FOREIGN,
    ),
]


class Command(BaseCommand):
    help = "Создаёт демонстрационные простои (по данным выгрузки)."

    def handle(self, *args, **options):
        try:
            workshop = Workshop.objects.get(enterprise__name=ENTERPRISE, name=WORKSHOP)
        except Workshop.DoesNotExist as exc:
            raise CommandError(
                "Сначала выполните: python manage.py seed_catalog (нет цеха ТЭСЦ-4)."
            ) from exc

        created = 0
        for (
            external_id, start, end, section_name, unit_name, note, fio,
            cat_code, sub_code, status, fault_side,
        ) in DEMO_EVENTS:
            if DowntimeEvent.objects.filter(
                source=DowntimeEvent.Source.FILE, external_id=external_id
            ).exists():
                continue

            section = Section.objects.get(workshop=workshop, name=section_name)
            unit = Unit.objects.get(section=section, name=unit_name)
            category = ItFaultCategory.objects.get(code=cat_code) if cat_code else None
            subcategory = ItFaultSubcategory.objects.get(code=sub_code) if sub_code else None

            event = DowntimeEvent(
                started_at=timezone.make_aware(datetime.strptime(start, "%Y-%m-%d %H:%M")),
                ended_at=timezone.make_aware(datetime.strptime(end, "%Y-%m-%d %H:%M")),
                workshop=workshop,
                section=section,
                unit=unit,
                note=note,
                recorded_by_name=fio,
                fault_category=category,
                fault_subcategory=subcategory,
                status=status,
                fault_side=fault_side,
                source=DowntimeEvent.Source.FILE,
                external_id=external_id,
            )
            save_with_audit(event, user=None)
            created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Демо-простои: создано {created}. Всего простоев: {DowntimeEvent.objects.count()}."
            )
        )
