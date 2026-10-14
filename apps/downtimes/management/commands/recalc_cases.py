"""Пересчёт границ и длительности всех кейсов.

Запуск:  python manage.py recalc_cases
Нужен, если состав кейсов меняли вручную или импортом и хотим пересчитать всё разом.
"""
from django.core.management.base import BaseCommand

from apps.downtimes.models import DowntimeCase
from apps.downtimes.services import recalc_case


class Command(BaseCommand):
    help = "Пересчитывает длительность и границы всех кейсов по их событиям."

    def handle(self, *args, **options):
        count = 0
        for case in DowntimeCase.objects.all():
            recalc_case(case)
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Пересчитано кейсов: {count}."))
