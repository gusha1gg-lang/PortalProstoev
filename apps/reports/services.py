"""
Сборка данных для дашбордов и отчётов.

Здесь нет новых формул: потери, доступность, MTTR/MTBF и штрафы считает модуль `sla`
(см. apps/sla/services.py). Этот модуль только складывает результаты по цехам
и готовит срезы (по категориям, по цехам, по месяцам) для страниц и выгрузки.

Так формулы живут в одном месте — отчёт для руководства, дашборд и страница SLA
всегда показывают одинаковые цифры.
"""
from collections import defaultdict
from decimal import Decimal

from apps.catalog.models import Workshop
from apps.sla.services import incidents_for, period_bounds, sla_summary

MONEY = Decimal("0.01")
ZERO = Decimal("0")


def _workshops(workshop=None):
    """Список активных цехов (или один выбранный)."""
    queryset = Workshop.objects.filter(is_active=True)
    if workshop is not None:
        queryset = queryset.filter(pk=workshop.pk)
    return list(queryset.order_by("name"))


def _sum(values):
    """Сумма с гарантированным нулём (Decimal)."""
    return sum(values, ZERO)


def _percent(part, whole):
    """Процент (part/whole), безопасный к делению на ноль."""
    if not whole:
        return Decimal("100") if part is not None else ZERO
    return (Decimal(part) / Decimal(whole) * 100).quantize(MONEY)


def _all_downtime_min(workshop, start, end):
    """Простои всех служб (не только ИТ) за период — для показателя «доля по вине ИТ»."""
    return sum(i["duration_min"] for i in incidents_for(workshop, start, end, it_only=False))


def kpi(year, month, workshop=None):
    """
    Главные показатели за месяц.

    Возвращает словарь: итоги по всем выбранным цехам + построчные данные
    (по цеху) + общий список инцидентов (для топ-причин и выгрузки).
    """
    start, end = period_bounds(year, month)
    period_min = int((end - start).total_seconds() // 60)

    workshops = _workshops(workshop)
    rows = [sla_summary(item, year, month) for item in workshops]

    total_period = period_min * len(rows)
    downtime = sum(r["downtime_min"] for r in rows)
    count = sum(r["incident_count"] for r in rows)
    loss = _sum(r["total_loss"] for r in rows)
    penalty = _sum(r["penalty"] for r in rows)
    incidents = [i for r in rows for i in r["incidents"]]

    all_downtime = sum(_all_downtime_min(item, start, end) for item in workshops)

    return {
        "year": year,
        "month": month,
        "period_min": period_min,
        "total_period_min": total_period,
        "rows": rows,
        "incidents": incidents,
        "incident_count": count,
        "downtime_min": downtime,
        "downtime_hours": (Decimal(downtime) / Decimal(60)).quantize(Decimal("0.1")),
        "loss": loss.quantize(MONEY),
        "penalty": penalty.quantize(MONEY),
        "availability": _percent(total_period - downtime, total_period),
        "mttr_min": (Decimal(downtime) / Decimal(count)).quantize(Decimal("0.1")) if count else ZERO,
        "mtbf_min": (
            (Decimal(total_period - downtime) / Decimal(count)).quantize(Decimal("0.1")) if count else ZERO
        ),
        "it_share": _percent(downtime, all_downtime) if all_downtime else Decimal("100.00"),
        "missing_rate": any(r["missing_rate"] for r in rows),
    }


def top_categories(incidents, limit=8):
    """Топ причин (категорий вины) по суммарному времени простоя."""
    aggregate = defaultdict(lambda: {"minutes": 0, "count": 0, "loss": ZERO})
    for incident in incidents:
        key = incident.get("category") or "Без категории"
        aggregate[key]["minutes"] += incident["duration_min"]
        aggregate[key]["count"] += 1
        aggregate[key]["loss"] += incident["loss"].amount

    result = [
        {"name": name, "minutes": values["minutes"], "count": values["count"], "loss": values["loss"]}
        for name, values in aggregate.items()
    ]
    result.sort(key=lambda item: item["minutes"], reverse=True)
    return result[:limit]


def monthly_series(year, month, workshop=None, months=6):
    """
    Ряд по месяцам (для графика): потери и время простоев за последние `months` месяцев,
    заканчивая указанным месяцем. Идём от старого к новому.
    """
    periods = []
    current_year, current_month = year, month
    for _ in range(months):
        periods.append((current_year, current_month))
        current_month -= 1
        if current_month == 0:
            current_month = 12
            current_year -= 1
    periods.reverse()

    series = []
    for period_year, period_month in periods:
        data = kpi(period_year, period_month, workshop=workshop)
        series.append(
            {
                "label": f"{period_month:02d}.{period_year}",
                "downtime_min": data["downtime_min"],
                "incident_count": data["incident_count"],
                "loss": float(data["loss"]),
            }
        )
    return series


def workshop_breakdown(rows, limit=8):
    """Разбивка по цехам (для графика): берём цеха с ненулевым временем."""
    items = [
        {
            "name": row["workshop"].name,
            "downtime_min": row["downtime_min"],
            "loss": float(row["total_loss"]),
            "incident_count": row["incident_count"],
        }
        for row in rows
        if row["downtime_min"] or row["total_loss"]
    ]
    items.sort(key=lambda item: item["downtime_min"], reverse=True)
    return items[:limit]


def incident_rows(year, month, workshop=None):
    """Плоский список инцидентов за период — для выгрузки в файл (CSV)."""
    data = kpi(year, month, workshop=workshop)
    rows = []
    for incident in data["incidents"]:
        rows.append(
            {
                "period": f"{year:04d}-{month:02d}",
                "workshop": incident["workshop"],
                "kind": "Кейс" if incident["kind"] == "case" else "Простой",
                "when": incident["when"],
                "title": incident["title"],
                "category": incident["category"],
                "duration_min": incident["duration_min"],
                "loss": incident["loss"].amount,
            }
        )
    return rows
