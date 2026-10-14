"""Начальные данные: создаём группы-роли портала."""
from django.db import migrations

from apps.accounts.roles import ALL_ROLES


def create_roles(apps, schema_editor):
    """Создаёт группы для каждой роли, если их ещё нет."""
    Group = apps.get_model("auth", "Group")
    for role_name in ALL_ROLES:
        Group.objects.get_or_create(name=role_name)


def remove_roles(apps, schema_editor):
    """Откат миграции: удаляем созданные группы."""
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=ALL_ROLES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_roles, remove_roles),
    ]
