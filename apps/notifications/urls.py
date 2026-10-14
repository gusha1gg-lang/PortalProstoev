"""Маршруты модуля «Уведомления»."""
from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.log_list, name="log"),
]
