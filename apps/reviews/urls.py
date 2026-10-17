"""Маршруты модуля «Разбор простоя» (этап 11.7)."""
from django.urls import path

from . import views

app_name = "reviews"

urlpatterns = [
    path("", views.review_list, name="list"),
    path("new/", views.review_create, name="create"),
    path("<int:pk>/", views.review_detail, name="detail"),
    path("<int:pk>/status/", views.status_change, name="status"),
    path("<int:pk>/timeline/add/", views.timeline_add, name="timeline_add"),
    path("<int:pk>/timeline/<int:entry_pk>/delete/", views.timeline_delete, name="timeline_delete"),
    path("<int:pk>/messages/add/", views.message_add, name="message_add"),
    path("<int:pk>/messages/<int:message_pk>/delete/", views.message_delete, name="message_delete"),
    path("<int:pk>/participants/add/", views.participant_add, name="participant_add"),
    path("<int:pk>/participants/<int:user_pk>/remove/", views.participant_remove, name="participant_remove"),
]
