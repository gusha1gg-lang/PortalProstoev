#!/usr/bin/env python
"""Точка входа Django: через него запускаются все команды.

Примеры:
    python manage.py runserver      # запустить локальный сервер
    python manage.py migrate        # применить изменения структуры БД
    python manage.py createsuperuser
"""
import os
import sys


def main():
    # По умолчанию используем настройки для разработки (config/settings/dev.py).
    # На проде значение DJANGO_SETTINGS_MODULE задаётся в окружении.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django не установлен. Активируйте виртуальное окружение и установите "
            "зависимости: pip install -r requirements.txt"
        ) from exc

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
