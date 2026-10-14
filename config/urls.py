"""Корневая маршрутизация URL проекта."""
from django.contrib import admin
from django.urls import include, path

from config.views import home

urlpatterns = [
    path("admin/", admin.site.urls),           # стандартная админка Django
    path("sla/", include("apps.sla.urls")),     # отчёт по потерям и SLA
    path("", home, name="home"),                # временная главная страница-заглушка
]
