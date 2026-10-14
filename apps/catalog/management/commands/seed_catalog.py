"""Команда наполнения справочников демонстрационными данными.

Запуск:  python manage.py seed_catalog
Идемпотентна: повторный запуск не создаёт дублей.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.catalog.models import (
    Equipment,
    ItFaultCategory,
    ItFaultSubcategory,
    LossRate,
    ProductionLine,
    Workshop,
)


class Command(BaseCommand):
    help = "Создаёт тестовые справочники (цеха, линии, оборудование, категории вины, ставки)."

    def handle(self, *args, **options):
        workshops = [
            ("C1", "Цех №1 — прокат"),
            ("C2", "Цех №2 — плавка"),
        ]
        lines_by_workshop = {
            "C1": [("L1", "Линия проката №1"), ("L2", "Линия проката №2")],
            "C2": [("L1", "Линия плавки №1")],
        }
        equipment_by_line = {
            "C1/L1": [("EQ1", "Стан горячей прокатки", "critical"), ("EQ2", "Моталка", "high")],
            "C1/L2": [("EQ1", "Стан холодной прокатки", "high")],
            "C2/L1": [("EQ1", "Печь плавки", "critical")],
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
        # Ставка потерь: линия -> (₽/час, маржа за тонну)
        rates = {
            "C1/L1": (Decimal("120000.00"), Decimal("3500.00")),
            "C1/L2": (Decimal("90000.00"), Decimal("2800.00")),
            "C2/L1": (Decimal("150000.00"), Decimal("4200.00")),
        }

        for code, name in workshops:
            Workshop.objects.get_or_create(code=code, defaults={"name": name})

        for ws_code, lines in lines_by_workshop.items():
            workshop = Workshop.objects.get(code=ws_code)
            for code, name in lines:
                ProductionLine.objects.get_or_create(
                    workshop=workshop, code=code, defaults={"name": name}
                )

        for line_key, items in equipment_by_line.items():
            ws_code, line_code = line_key.split("/")
            line = ProductionLine.objects.get(workshop__code=ws_code, code=line_code)
            for code, name, criticality in items:
                Equipment.objects.get_or_create(
                    line=line, code=code, defaults={"name": name, "criticality": criticality}
                )

        for code, name in categories:
            ItFaultCategory.objects.get_or_create(code=code, defaults={"name": name})

        for cat_code, subs in subcategories.items():
            category = ItFaultCategory.objects.get(code=cat_code)
            for code, name in subs:
                ItFaultSubcategory.objects.get_or_create(
                    category=category, code=code, defaults={"name": name}
                )

        for line_key, (cost, ton) in rates.items():
            ws_code, line_code = line_key.split("/")
            line = ProductionLine.objects.get(workshop__code=ws_code, code=line_code)
            LossRate.objects.get_or_create(
                line=line,
                valid_from="2025-01-01",
                defaults={"cost_per_hour": cost, "ton_margin": ton, "note": "Демо-ставка"},
            )

        self.stdout.write(self.style.SUCCESS("Справочники заполнены демо-данными."))
