"""
Раздел «Простои» (этап 11.7): список простоев и карточка одного простоя.

Раньше простои были видны только в админке Django. Теперь у них есть обычная страница
портала — список с фильтрами и карточка записи со всеми деталями, связанными тикетами
и историей изменений. Карточка — «дверь» к разбору простоя (следующий шаг).

Просмотр доступен любому вошедшему сотруднику (как дашборд и отчёты).
"""
from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from apps.catalog.models import ItFaultCategory, Workshop
from apps.reviews.permissions import can_manage_reviews
from apps.reviews.services import eligible_leads

from .models import DowntimeEvent

# Сколько простоев показывать на одной странице списка.
LIST_PER_PAGE = 50

# Сколько записей истории показывать в карточке.
LOG_LIMIT = 50


def _parse_date(value):
    """Аккуратно превращает «ГГГГ-ММ-ДД» в дату. Пустое или мусор — None (фильтр не применяется)."""
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _log_rows(logs):
    """Готовит историю изменений к показу.

    В базе изменения хранятся как {поле: {было, стало}}. Здесь превращаем их в простой
    список троек (поле, было, стало) — чтобы шаблон не разбирал вложенные словари.
    """
    rows = []
    for entry in logs:
        changes = []
        for label, diff in (entry.changes or {}).items():
            if isinstance(diff, dict):
                changes.append((label, diff.get("было", ""), diff.get("стало", "")))
            else:
                changes.append((label, "", diff))
        rows.append(
            {
                "created_at": entry.created_at,
                "user": entry.user,
                "action": entry.get_action_display(),
                "comment": entry.comment,
                "changes": changes,
            }
        )
    return rows


@login_required
def downtime_list(request):
    """Список простоев с фильтрами и постраничным показом."""
    events = (
        DowntimeEvent.objects.select_related(
            "workshop", "section", "unit", "fault_category", "fault_subcategory", "case"
        )
        .order_by("-started_at")
    )

    get = request.GET
    filters = {
        "date_from": (get.get("date_from") or "").strip(),
        "date_to": (get.get("date_to") or "").strip(),
        "workshop": (get.get("workshop") or "").strip(),
        "category": (get.get("category") or "").strip(),
        "status": (get.get("status") or "").strip(),
        "fault_side": (get.get("fault_side") or "").strip(),
        "source": (get.get("source") or "").strip(),
        "q": (get.get("q") or "").strip(),
        "needs_review": get.get("needs_review") == "1",
    }

    date_from = _parse_date(filters["date_from"])
    date_to = _parse_date(filters["date_to"])
    if date_from:
        events = events.filter(started_at__date__gte=date_from)
    if date_to:
        events = events.filter(started_at__date__lte=date_to)
    if filters["workshop"].isdigit():
        events = events.filter(workshop_id=filters["workshop"])
    if filters["category"].isdigit():
        events = events.filter(fault_category_id=filters["category"])
    if filters["status"]:
        events = events.filter(status=filters["status"])
    if filters["fault_side"]:
        events = events.filter(fault_side=filters["fault_side"])
    if filters["source"]:
        events = events.filter(source=filters["source"])
    if filters["needs_review"]:
        events = events.filter(needs_review=True)
    if filters["q"]:
        events = events.filter(
            Q(note__icontains=filters["q"]) | Q(recorded_by_name__icontains=filters["q"])
        )

    total = events.count()
    page = Paginator(events, LIST_PER_PAGE).get_page(request.GET.get("page"))

    # Строка фильтров без номера страницы — чтобы переход «назад/вперёд» сохранял выбор.
    params = request.GET.copy()
    params.pop("page", None)

    context = {
        "page": page,
        "total": total,
        "filters": filters,
        "querystring": params.urlencode(),
        "workshops": Workshop.objects.filter(is_active=True).order_by("name"),
        "categories": ItFaultCategory.objects.filter(is_active=True).order_by("name"),
        "statuses": DowntimeEvent.Status.choices,
        "fault_sides": DowntimeEvent.FaultSide.choices,
        "sources": DowntimeEvent.Source.choices,
        "can_manage": can_manage_reviews(request.user),
        "leads": eligible_leads(),
    }
    return render(request, "downtimes/list.html", context)


@login_required
def downtime_detail(request, pk):
    """Карточка одного простоя: все детали, связанные тикеты и история изменений."""
    event = get_object_or_404(
        DowntimeEvent.objects.select_related(
            "workshop", "section", "unit", "fault_category", "fault_subcategory", "case"
        ),
        pk=pk,
    )

    # Тикеты самого простоя и тикеты его инцидента (кейса) — если простой объединён.
    tickets = list(event.ticket_links.all())
    if event.case_id:
        tickets += list(event.case.ticket_links.all())

    context = {
        "event": event,
        "logs": _log_rows(event.logs.select_related("user")[:LOG_LIMIT]),
        "tickets": tickets,
    }
    return render(request, "downtimes/card.html", context)
