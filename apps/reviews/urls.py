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
    path("<int:pk>/approval/decide/", views.approval_decide, name="approval_decide"),
    path("<int:pk>/approvers/<int:user_pk>/toggle/", views.approver_toggle, name="approver_toggle"),
    path("<int:pk>/actions/add/", views.action_add, name="action_add"),
    path("<int:pk>/actions/<int:action_pk>/edit/", views.action_edit, name="action_edit"),
    path("<int:pk>/actions/<int:action_pk>/status/", views.action_status, name="action_status"),
    path("<int:pk>/actions/<int:action_pk>/delete/", views.action_delete, name="action_delete"),
    path("<int:pk>/actions/<int:action_pk>/send/", views.action_send_ticket, name="action_send"),
    path("templates/", views.template_list, name="templates"),
    path("templates/add/", views.template_add, name="template_add"),
    path("templates/<int:pk>/edit/", views.template_edit, name="template_edit"),
    path("templates/<int:pk>/toggle/", views.template_toggle, name="template_toggle"),
]
