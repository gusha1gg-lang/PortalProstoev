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

# Логин → (имя, роль портала, почта для демонстрации писем).
# Почта условная: в разработке письма не уходят наружу, а печатаются в консоль.
DEMO_USERS = [
    ("operator", ("Оператор смены", ROLE_OPERATOR, "operator@example.local")),
    ("specialist", ("Специалист по простоям", ROLE_DOWNTIME_SPECIALIST, "specialist@example.local")),
    ("it_manager", ("Руководитель ИТ", ROLE_IT_MANAGER, "it_manager@example.local")),
    ("management", ("Руководство предприятия", ROLE_MANAGEMENT, "management@example.local")),
]


class Command(BaseCommand):
    help = "Создаёт демонстрационных пользователей по ролям (только для разработки)."

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        created_count = 0

        for username, (full_name, role, email) in DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"first_name": full_name, "is_staff": False, "email": email},
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
                created_count += 1
            elif not user.email:
                # У пользователей, созданных раньше, почты не было — добавим для показа писем.
                user.email = email
                user.save(update_fields=["email"])

            group = Group.objects.filter(name=role).first()
            if group is not None:
                user.groups.add(group)

        self.stdout.write(
            self.style.SUCCESS(
                f"Пользователей создано: {created_count}. "
                f"Пароль для всех: {DEMO_PASSWORD} (только для разработки)."
            )
        )
