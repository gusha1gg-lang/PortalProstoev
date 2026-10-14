"""
Демонстрационные пользователи портала по ролям (для разработки).

    python manage.py seed_users

На проде пользователи приходят из AD (ADFS), поэтому создавать их вручную
не нужно — эта команда только для локальной работы и показа ролей.
Пароль у всех демо-пользователей один: DevPortal2026! (только для dev!).
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.roles import (
    ROLE_DOWNTIME_SPECIALIST,
    ROLE_IT_MANAGER,
    ROLE_MANAGEMENT,
    ROLE_OPERATOR,
)

DEMO_PASSWORD = "DevPortal2026!"

# Логин → (имя, роль портала)
DEMO_USERS = [
    ("operator", ("Оператор смены", ROLE_OPERATOR)),
    ("specialist", ("Специалист по простоям", ROLE_DOWNTIME_SPECIALIST)),
    ("it_manager", ("Руководитель ИТ", ROLE_IT_MANAGER)),
    ("management", ("Руководство предприятия", ROLE_MANAGEMENT)),
]


class Command(BaseCommand):
    help = "Создаёт демонстрационных пользователей по ролям (только для разработки)."

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        created_count = 0

        for username, (full_name, role) in DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"first_name": full_name, "is_staff": False},
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
                created_count += 1

            group = Group.objects.filter(name=role).first()
            if group is not None:
                user.groups.add(group)

        self.stdout.write(
            self.style.SUCCESS(
                f"Пользователей создано: {created_count}. "
                f"Пароль для всех: {DEMO_PASSWORD} (только для разработки)."
            )
        )
