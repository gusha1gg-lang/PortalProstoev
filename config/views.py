"""Простые общие страницы проекта (не относятся к конкретному модулю)."""
from django.shortcuts import render


def home(request):
    """Главная страница-заглушка. Позже заменим на дашборд портала."""
    return render(request, "home.html")
