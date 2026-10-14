"""
Проверка настройки почты: отправляет тестовое письмо на адрес.

    python manage.py notify_test --to me@example.local

В разработке письмо печатается в консоль (Django console-backend), на проде уходит
через SMTP. Удобно, чтобы вместе с коллегами из ПИ-ПС проверить почтовый сервис.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.notifications.services import send_test


class Command(BaseCommand):
    help = "Отправляет проверочное письмо на указанный адрес."

    def add_arguments(self, parser):
        parser.add_argument("--to", required=True, help="Адрес получателя проверочного письма")

    def handle(self, *args, **options):
        result = send_test(options["to"])
        if result == "sent":
            self.stdout.write(self.style.SUCCESS(f"Письмо отправлено на {options['to']}"))
        else:
            raise CommandError(f"Не удалось отправить письмо: {result}")
