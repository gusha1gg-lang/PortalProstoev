"""Маршруты модуля «Отчёты и дашборды»."""
from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("reports/sla/", views.sla_report, name="sla_report"),
    path("reports/export/", views.export_csv, name="export_csv"),
    path("reports/export/xlsx/", views.export_xlsx, name="export_xlsx"),
    path("reports/chart-data/", views.chart_data, name="chart_data"),
]
