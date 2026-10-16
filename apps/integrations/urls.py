"""Маршруты страницы синхронизации (этап 11.6)."""
from django.urls import path

from . import views

app_name = "integrations"

urlpatterns = [
    path("", views.sync_page, name="sync"),
    path("now/", views.sync_now, name="sync_now"),
    path("close-period/", views.close_period, name="close_period"),
    path("review/", views.review_list, name="review"),
    path("review/<int:pk>/accept/", views.review_accept, name="review_accept"),
]
