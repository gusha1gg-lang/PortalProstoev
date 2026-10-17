"""Маршруты раздела «Простои» (этап 11.7)."""
from django.urls import path

from . import views

app_name = "downtimes"

urlpatterns = [
    path("", views.downtime_list, name="list"),
    path("<int:pk>/", views.downtime_detail, name="detail"),
]
