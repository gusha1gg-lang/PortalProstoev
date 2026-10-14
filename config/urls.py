"""Корневая маршрутизация URL проекта."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),                     # стандартная админка Django
    path("accounts/", include("apps.accounts.urls")),    # вход/выход
    path("sla/", include("apps.sla.urls")),              # расчёт потерь и SLA
    path("notifications/", include("apps.notifications.urls")),  # журнал уведомлений
    path("", include("apps.reports.urls")),              # дашборд (главная), SLA-отчёт, выгрузка
]
