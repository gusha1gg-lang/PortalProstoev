"""Маршруты справочников в портале (этап 11.6)."""
from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    # Классификация вины ИТ (категория → причина)
    path("", views.classification, name="classification"),
    path("category/add/", views.category_add, name="category_add"),
    path("category/<int:pk>/", views.category_edit, name="category"),
    path("category/<int:pk>/toggle/", views.category_toggle, name="category_toggle"),
    path("category/<int:pk>/reason/add/", views.subcategory_add, name="subcategory_add"),
    path("reason/<int:pk>/edit/", views.subcategory_edit, name="subcategory_edit"),
    path("reason/<int:pk>/toggle/", views.subcategory_toggle, name="subcategory_toggle"),

    # Производственная структура: цеха → участки → агрегаты
    path("structure/", views.structure, name="structure"),
    path("structure/workshop/add/", views.workshop_add, name="workshop_add"),
    path("structure/workshop/<int:pk>/", views.workshop_edit, name="workshop"),
    path("structure/workshop/<int:pk>/toggle/", views.workshop_toggle, name="workshop_toggle"),
    path("structure/workshop/<int:pk>/section/add/", views.section_add, name="section_add"),
    path(
        "structure/workshop/<int:pk>/unit/add/",
        views.workshop_unit_add,
        name="workshop_unit_add",
    ),
    path("structure/section/<int:pk>/", views.section_edit, name="section"),
    path("structure/section/<int:pk>/toggle/", views.section_toggle, name="section_toggle"),
    path("structure/section/<int:pk>/unit/add/", views.section_unit_add, name="section_unit_add"),
    path("structure/unit/<int:pk>/edit/", views.unit_edit, name="unit_edit"),
    path("structure/unit/<int:pk>/toggle/", views.unit_toggle, name="unit_toggle"),
]
