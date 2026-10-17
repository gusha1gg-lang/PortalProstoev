"""Маршруты модуля «Разбор простоя» (этап 11.7)."""
from django.urls import path

from . import views

app_name = "reviews"

urlpatterns = [
    path("", views.review_list, name="list"),
    path("new/", views.review_create, name="create"),
    path("<int:pk>/", views.review_detail, name="detail"),
]
