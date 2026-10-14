"""
Подготовка демонстрационного стенда одной командой.

    python manage.py seed_demo

Последовательно наполняет портал демонстрационными данными: справочники, простои,
договоры SLA, правила уведомлений и пользователей по ролям. Команда безопасна для
повторного запуска (ничего не дублирует).

Удобно, когда нужно быстро восстановить стенд перед показом.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand

# Порядок важен: сначала справочники, затем данные, которые на них опираются.
STEPS = [
    ("seed_catalog", "Справочники: предприятия, цеха, участки, категории вины, ставки"),
    ("seed_downtimes", "Демонстрационные простои"),
    ("seed_sla", "Договоры SLA"),
    ("seed_notifications", "Правила уведомлений и получатели"),
    ("seed_users", "Пользователи по ролям (только для разработки)"),
]


class Command(BaseCommand):
    help = "Готовит полный демонстрационный стенд (все seed-команды по порядку)."

    def handle(self, *args, **options):
        for command_name, description in STEPS:
            self.stdout.write(self.style.MIGRATE_HEADING(f"→ {command_name}: {description}"))
            call_command(command_name)

        self.stdout.write(self.style.SUCCESS("Демонстрационный стенд готов."))
        self.stdout.write(
            "Далее: python manage.py runserver  и открыть http://127.0.0.1:8000/ "
            "(вход — демо-пользователи, пароль DevPortal2026!)."
        )
