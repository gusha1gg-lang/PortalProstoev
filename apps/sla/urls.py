"""Маршруты модуля «Потери и SLA»."""
from django.urls import path

from . import views

app_name = "sla"

urlpatterns = [
    path("", views.report, name="report"),
]
