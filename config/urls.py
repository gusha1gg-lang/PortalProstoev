"""Корневая маршрутизация URL проекта."""
from django.contrib import admin
from django.urls import path

from config.views import home

urlpatterns = [
    path("admin/", admin.site.urls),   # стандартная админка Django
    path("", home, name="home"),       # временная главная страница-заглушка
]
