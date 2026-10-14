"""Простая страница отчёта по потерям и SLA (без JS — обычный HTML-список)."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from apps.catalog.models import Enterprise

from .services import sla_summary


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


@login_required
def report(request):
    """Отчёт за месяц: по каждому предприятию — потери, доступность, MTTR/MTBF, штраф."""
    today = timezone.localdate()
    period = request.GET.get("period") or f"{today.year:04d}-{today.month:02d}"
    year, month = _parse_period(period)
    period = f"{year:04d}-{month:02d}"

    enterprises = Enterprise.objects.filter(is_active=True).order_by("name")
    rows = [sla_summary(enterprise, year, month) for enterprise in enterprises]

    # Итоги по всем предприятиям.
    totals = {
        "incident_count": sum(r["incident_count"] for r in rows),
        "total_loss": sum((r["total_loss"] for r in rows), 0),
        "penalty": sum((r["penalty"] for r in rows), 0),
    }

    context = {"period": period, "rows": rows, "totals": totals}
    return render(request, "sla/report.html", context)
