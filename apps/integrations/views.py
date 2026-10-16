"""
Страницы синхронизации (этап 11.6):

    «Забрать сейчас»   — ручной запуск за последние дни;
    «Закрыть период»   — закрытые периоды не изменяются при импорте;
    «на проверку»       — записи, которые источник поправил/снял (их надо подтвердить).
"""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.decorators import role_required
from apps.accounts.roles import ROLE_ADMIN, ROLE_DOWNTIME_SPECIALIST, ROLE_IT_MANAGER
from apps.downtimes.models import DowntimeEvent, ReportingPeriod
from apps.downtimes.services import save_with_audit

from .models import SyncRun
from .services import sync_downtimes

# Кто может запускать синхронизацию, закрывать периоды и подтверждать проверку.
SYNC_ROLES = (ROLE_DOWNTIME_SPECIALIST, ROLE_IT_MANAGER, ROLE_ADMIN)

# Окно кнопки «Забрать сейчас» — за сколько дней забираем данные.
MANUAL_WINDOW_DAYS = 7

# Сколько показывать в списках на странице.
LIST_LIMIT = 50


@login_required
@role_required(*SYNC_ROLES)
def sync_page(request):
    """Главная страница синхронизации: запуски, кнопки, закрытые периоды."""
    context = {
        "runs": SyncRun.objects.all()[:20],
        "periods": ReportingPeriod.objects.all()[:24],
        "review_count": DowntimeEvent.objects.filter(needs_review=True).count(),
        "window_days": MANUAL_WINDOW_DAYS,
        "current_year": timezone.now().year,
        "current_month": timezone.now().month,
        "months": [
            (1, "январь"), (2, "февраль"), (3, "март"), (4, "апрель"),
            (5, "май"), (6, "июнь"), (7, "июль"), (8, "август"),
            (9, "сентябрь"), (10, "октябрь"), (11, "ноябрь"), (12, "декабрь"),
        ],
    }
    return render(request, "integrations/sync.html", context)


@login_required
@role_required(*SYNC_ROLES)
def sync_now(request):
    """Кнопка «Забрать сейчас»: ручной запуск синхронизации за последние дни."""
    if request.method != "POST":
        return redirect("integrations:sync")

    until = timezone.now()
    since = until - timedelta(days=MANUAL_WINDOW_DAYS)
    try:
        report, run = sync_downtimes(
            since=since,
            until=until,
            mode=SyncRun.Mode.MANUAL,
            user=request.user,
            notify=False,
        )
    except Exception as exc:  # noqa: BLE001 — ошибка источника не должна ронять страницу
        messages.error(request, f"Не удалось забрать данные: {exc}")
        return redirect("integrations:sync")

    if run.status == SyncRun.Status.ERROR:
        messages.error(request, run.report)
    else:
        summary = report.as_text().replace("\n", " · ")
        if report.review:
            messages.warning(request, f"Синхронизация выполнена. На проверку: {report.review}. {summary}")
        else:
            messages.success(request, f"Синхронизация выполнена. {summary}")
    return redirect("integrations:sync")


@login_required
@role_required(*SYNC_ROLES)
def close_period(request):
    """Кнопка «Закрыть период»: простой этого месяца больше не изменяется при импорте."""
    if request.method != "POST":
        return redirect("integrations:sync")

    try:
        year = int(request.POST.get("year", ""))
        month = int(request.POST.get("month", ""))
    except (TypeError, ValueError):
        messages.error(request, "Укажите год и месяц.")
        return redirect("integrations:sync")

    if not (1 <= month <= 12 and 2000 <= year <= 2100):
        messages.error(request, "Год и месяц указаны некорректно.")
        return redirect("integrations:sync")

    period, created = ReportingPeriod.objects.get_or_create(
        year=year, month=month, defaults={"closed_by": request.user}
    )
    label = f"{year:04d}-{month:02d}"
    if created:
        messages.success(request, f"Период {label} закрыт. Его простои больше не изменяются.")
    else:
        messages.info(request, f"Период {label} уже был закрыт.")
    return redirect("integrations:sync")


@login_required
@role_required(*SYNC_ROLES)
def review_list(request):
    """Список «на проверку»: записи, которые источник поправил или снял."""
    events = (
        DowntimeEvent.objects.filter(needs_review=True)
        .select_related("workshop", "section", "unit", "fault_category", "fault_subcategory")
        .order_by("-started_at")[:LIST_LIMIT]
    )
    context = {
        "events": events,
        "total": DowntimeEvent.objects.filter(needs_review=True).count(),
    }
    return render(request, "integrations/review.html", context)


@login_required
@role_required(*SYNC_ROLES)
def review_accept(request, pk):
    """Подтвердить результат сверки: снять с проверки.

    Отметка («Исправлен»/«Снят»/«Скорректирован») остаётся — это история записи.
    """
    if request.method != "POST":
        return redirect("integrations:review")

    event = get_object_or_404(DowntimeEvent, pk=pk)
    event.needs_review = False
    save_with_audit(event, user=request.user, comment="Проверка: результат сверки принят")
    messages.success(request, "Запись подтверждена и снята с проверки.")
    return redirect("integrations:review")
