"""
Страницы отчётов: дашборд, отчёт по SLA для заказчика и выгрузка в файл.

Период задаётся параметром `?period=ГГГГ-ММ` (по умолчанию — текущий месяц),
предприятие — необязательным `?enterprise=<id>`.
"""
import csv
import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.catalog.models import Enterprise

from .services import enterprise_breakdown, incident_rows, kpi, monthly_series, top_categories


def _parse_period(raw: str):
    """Разбирает «YYYY-MM» в (год, месяц). При ошибке — текущий месяц."""
    today = timezone.localdate()
    try:
        year_text, month_text = raw.split("-")
        year, month = int(year_text), int(month_text)
        if not (1 <= month <= 12):
            raise ValueError
        return year, month
    except (ValueError, AttributeError):
        return today.year, today.month


def _period_and_enterprise(request):
    """Достаёт из запроса период и (необязательное) предприятие."""
    today = timezone.localdate()
    period = request.GET.get("period") or f"{today.year:04d}-{today.month:02d}"
    year, month = _parse_period(period)
    period = f"{year:04d}-{month:02d}"

    enterprise = None
    enterprise_id = request.GET.get("enterprise")
    if enterprise_id:
        enterprise = Enterprise.objects.filter(pk=enterprise_id, is_active=True).first()

    return period, year, month, enterprise


@login_required
def dashboard(request):
    """Главная страница: KPI, графики и срезы за выбранный период."""
    period, year, month, enterprise = _period_and_enterprise(request)

    data = kpi(year, month, enterprise=enterprise)
    series = monthly_series(year, month, enterprise=enterprise, months=6)
    categories = top_categories(data["incidents"])
    breakdown = enterprise_breakdown(data["rows"])

    # Данные для графиков: подписи и значения (часы считаем здесь, чтобы в шаблоне не делить).
    series_chart = {
        "labels": [item["label"] for item in series],
        "downtime_hours": [round(item["downtime_min"] / 60, 1) for item in series],
        "loss": [item["loss"] for item in series],
    }
    categories_chart = {
        "labels": [item["name"] for item in categories],
        "minutes": [item["minutes"] for item in categories],
    }
    breakdown_chart = {
        "labels": [item["name"] for item in breakdown],
        "loss": [item["loss"] for item in breakdown],
    }

    context = {
        "period": period,
        "year": year,
        "month": month,
        "enterprise": enterprise,
        "enterprises": Enterprise.objects.filter(is_active=True).order_by("name"),
        "kpi": data,
        "series": series,
        "categories": categories,
        "breakdown": breakdown,
        "series_chart": series_chart,
        "categories_chart": categories_chart,
        "breakdown_chart": breakdown_chart,
    }
    return render(request, "reports/dashboard.html", context)


@login_required
def sla_report(request):
    """Печатная страница «SLA-отчёт для заказчика»: по каждому предприятию и итоги."""
    period, year, month, enterprise = _period_and_enterprise(request)

    data = kpi(year, month, enterprise=enterprise)
    context = {
        "period": period,
        "enterprise": enterprise,
        "enterprises": Enterprise.objects.filter(is_active=True).order_by("name"),
        "generated_at": timezone.localtime(),
        "kpi": data,
    }
    return render(request, "reports/sla_report.html", context)


@login_required
def export_csv(request):
    """Выгрузка инцидентов за период в CSV (открывается в Excel, кодировка с BOM)."""
    period, year, month, enterprise = _period_and_enterprise(request)
    rows = incident_rows(year, month, enterprise=enterprise)

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="downtimes-{period}.csv"'
    response.write("\ufeff")  # BOM, чтобы Excel корректно открыл русский текст

    writer = csv.writer(response, delimiter=";")
    writer.writerow(EXPORT_HEADERS)
    for row in rows:
        writer.writerow(_export_row_values(row))
    return response


# Заголовки и порядок колонок — общие для CSV и Excel.
EXPORT_HEADERS = [
    "Период",
    "Предприятие",
    "Тип",
    "Дата",
    "Название",
    "Категория",
    "Длительность, мин",
    "Потери, ₽",
]


def _export_row_values(row):
    """Строка выгрузки в общем порядке колонок (для CSV и Excel)."""
    written = timezone.localtime(row["when"]) if timezone.is_aware(row["when"]) else row["when"]
    return [
        row["period"],
        row["enterprise"],
        row["kind"],
        written.strftime("%d.%m.%Y %H:%M"),
        row["title"],
        row["category"],
        row["duration_min"],
        f"{row['loss']:.2f}",
    ]


@login_required
def export_xlsx(request):
    """Выгрузка инцидентов за период в Excel (.xlsx) — по ответу руководителя (В20)."""
    openpyxl = _load_openpyxl()
    period, year, month, enterprise = _period_and_enterprise(request)
    rows = incident_rows(year, month, enterprise=enterprise)

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Простои"
    sheet.append(EXPORT_HEADERS)
    for row in rows:
        sheet.append(_export_row_values(row))

    # Немного удобства: жирная шапка и ширина колонок.
    for cell in sheet[1]:
        cell.font = openpyxl.styles.Font(bold=True)
    widths = [10, 22, 8, 18, 40, 24, 16, 14]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[openpyxl.utils.get_column_letter(index)].width = width

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="downtimes-{period}.xlsx"'
    workbook.save(response)
    return response


def _load_openpyxl():
    """Загружает openpyxl; если модуль не установлен — понятная ошибка с подсказкой."""
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise RuntimeError(
            "Для выгрузки в Excel нужен модуль openpyxl. Установите: pip install openpyxl"
        ) from exc
    return openpyxl


@login_required
def chart_data(request):
    """Данные для графиков в виде JSON (используется дашбордом при обновлении без перезагрузки)."""
    period, year, month, enterprise = _period_and_enterprise(request)
    data = kpi(year, month, enterprise=enterprise)
    payload = {
        "period": period,
        "totals": {"downtime_min": data["downtime_min"], "loss": float(data["loss"])},
        "series": monthly_series(year, month, enterprise=enterprise, months=6),
        "categories": [{"name": c["name"], "minutes": c["minutes"]} for c in top_categories(data["incidents"])],
        "breakdown": enterprise_breakdown(data["rows"]),
    }
    return HttpResponse(json.dumps(payload, ensure_ascii=False), content_type="application/json")
