"""Маршруты редактора классификации вины ИТ (этап 11.6)."""
from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("", views.classification, name="classification"),
    path("category/add/", views.category_add, name="category_add"),
    path("category/<int:pk>/", views.category_edit, name="category"),
    path("category/<int:pk>/toggle/", views.category_toggle, name="category_toggle"),
    path("category/<int:pk>/reason/add/", views.subcategory_add, name="subcategory_add"),
    path("reason/<int:pk>/edit/", views.subcategory_edit, name="subcategory_edit"),
    path("reason/<int:pk>/toggle/", views.subcategory_toggle, name="subcategory_toggle"),
]
