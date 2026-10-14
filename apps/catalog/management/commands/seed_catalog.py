"""Команда наполнения справочников демонстрационными данными.

Запуск:  python manage.py seed_catalog
Идемпотентна: повторный запуск не создаёт дублей.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.catalog.models import (
    ItFaultCategory,
    ItFaultSubcategory,
    LossRate,
    Section,
    Unit,
    Workshop,
)


class Command(BaseCommand):
    help = "Создаёт тестовые справочники (цеха, участки, агрегаты, категории вины, ставки)."

    def handle(self, *args, **options):
        workshops = [
            ("TESC4", "ТЭСЦ-4"),
            ("C2", "Цех №2 — плавка"),
        ]
        # Цех -> участки
        sections_by_workshop = {
            "TESC4": [
                ("U-Otd", "Участок отделки труб 1020"),
                ("U-Svar", "Участок сварки труб 1020"),
                ("U-Form", "Участок формовки труб 1020"),
                ("U-Gidro", "Участок ремонта и гидроиспытаний 1020"),
            ],
            "C2": [("U-Plav", "Участок плавки")],
        }
        # Участок -> агрегаты
        units_by_section = {
            "TESC4/U-Otd": [
                ("OPT9", "Площадка №9 окончательной приемки — ОПТ №9", "high"),
                ("AUZK31", "Участок АУЗК-31 — АУЗК-31", "medium"),
            ],
            "TESC4/U-Svar": [
                ("SSS3", "Ремонтная площадка №3 — ССС-3", "high"),
            ],
            "TESC4/U-Form": [
                ("KLEIM", "Участок клеймовки и накопителя — Участок клеймения труб", "high"),
            ],
            "TESC4/U-Gidro": [
                ("P9046-2", "Участок гидропресса №2 — П9046-2", "critical"),
            ],
            "C2/U-Plav": [
                ("PECH1", "Печь плавки", "critical"),
            ],
        }
        categories = [
            ("NET", "Сеть"),
            ("SRV", "Серверы и инфраструктура"),
            ("APP", "Прикладное ПО"),
            ("INT", "Интеграции и обмен данными"),
            ("DBA", "Базы данных"),
            ("SEC", "Информационная безопасность"),
            ("HUM", "Человеческий фактор"),
        ]
        subcategories = {
            "NET": [("NET-SW", "Сетевой коммутатор"), ("NET-UP", "Обрыв канала")],
            "SRV": [("SRV-AV", "Отказ сервера"), ("SRV-VM", "Проблема виртуализации")],
            "APP": [("APP-CR", "Падение приложения"), ("APP-SL", "Деградация скорости")],
            "INT": [("INT-IF", "Сбой интеграции"), ("INT-DL", "Задержка обмена")],
            "DBA": [("DBA-DW", "Отказ БД"), ("DBA-LK", "Блокировки")],
            "SEC": [("SEC-AT", "Инцидент ИБ")],
            "HUM": [("HUM-ER", "Ошибка оператора")],
        }
        # Ставка потерь: участок -> (₽/час, маржа за тонну)
        rates = {
            "TESC4/U-Otd": (Decimal("120000.00"), Decimal("3500.00")),
            "TESC4/U-Svar": (Decimal("90000.00"), Decimal("2800.00")),
            "TESC4/U-Form": (Decimal("120000.00"), Decimal("3500.00")),
            "TESC4/U-Gidro": (Decimal("150000.00"), Decimal("4200.00")),
        }

        for code, name in workshops:
            Workshop.objects.get_or_create(code=code, defaults={"name": name})

        for ws_code, sections in sections_by_workshop.items():
            workshop = Workshop.objects.get(code=ws_code)
            for code, name in sections:
                Section.objects.get_or_create(workshop=workshop, code=code, defaults={"name": name})

        for section_key, items in units_by_section.items():
            ws_code, sec_code = section_key.split("/")
            section = Section.objects.get(workshop__code=ws_code, code=sec_code)
            for code, name, criticality in items:
                Unit.objects.get_or_create(
                    section=section, code=code, defaults={"name": name, "criticality": criticality}
                )

        for code, name in categories:
            ItFaultCategory.objects.get_or_create(code=code, defaults={"name": name})

        for cat_code, subs in subcategories.items():
            category = ItFaultCategory.objects.get(code=cat_code)
            for code, name in subs:
                ItFaultSubcategory.objects.get_or_create(
                    category=category, code=code, defaults={"name": name}
                )

        for section_key, (cost, ton) in rates.items():
            ws_code, sec_code = section_key.split("/")
            section = Section.objects.get(workshop__code=ws_code, code=sec_code)
            LossRate.objects.get_or_create(
                section=section,
                valid_from="2025-01-01",
                defaults={"cost_per_hour": cost, "ton_margin": ton, "note": "Демо-ставка"},
            )

        self.stdout.write(self.style.SUCCESS("Справочники заполнены демо-данными."))
