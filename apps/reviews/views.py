"""
Страницы модуля «Разбор простоя» (этап 11.7, шаг 1).

Список разборов, карточка разбора и создание разбора из выбранных простоев.
Просмотр — любому вошедшему (как простои и отчёты). Создание и ведение — ролям
«Специалист по простоям», «Руководитель ИТ», «Администратор».
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.accounts.decorators import role_required
from apps.downtimes.models import DowntimeEvent

from .models import IncidentReview, TimelineEntry
from .permissions import REVIEW_ROLES, can_edit_review, can_manage_reviews
from .services import (
    add_timeline_entry,
    change_status,
    create_review_from_events,
    delete_timeline_entry,
    eligible_leads,
)

# Сколько разборов показывать на одной странице.
LIST_PER_PAGE = 50


def _resolve_lead(request):
    """Ведущий из формы. Если не выбран или не подходит — сам создатель разбора."""
    lead_id = (request.POST.get("lead") or "").strip()
    if lead_id.isdigit():
        candidate = eligible_leads().filter(pk=lead_id).first()
        if candidate:
            return candidate
    return request.user


@login_required
def review_list(request):
    """Список разборов с фильтрами по статусу, ведущему и поиском."""
    reviews = IncidentReview.objects.select_related("case", "lead").order_by("-created_at")

    get = request.GET
    filters = {
        "status": (get.get("status") or "").strip(),
        "lead": (get.get("lead") or "").strip(),
        "q": (get.get("q") or "").strip(),
    }
    if filters["status"]:
        reviews = reviews.filter(status=filters["status"])
    if filters["lead"].isdigit():
        reviews = reviews.filter(lead_id=filters["lead"])
    if filters["q"]:
        reviews = reviews.filter(
            Q(number__icontains=filters["q"])
            | Q(title__icontains=filters["q"])
            | Q(case__number__icontains=filters["q"])
            | Q(case__title__icontains=filters["q"])
        )

    total = reviews.count()
    page = Paginator(reviews, LIST_PER_PAGE).get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)

    context = {
        "page": page,
        "total": total,
        "filters": filters,
        "querystring": params.urlencode(),
        "statuses": IncidentReview.Status.choices,
        "leads": eligible_leads(),
        "can_manage": can_manage_reviews(request.user),
    }
    return render(request, "reviews/list.html", context)


@login_required
def review_detail(request, pk):
    """Карточка разбора: шапка, входящие простои, история инцидента."""
    review = get_object_or_404(
        IncidentReview.objects.select_related("case", "lead", "created_by"), pk=pk
    )
    events = review.events.select_related(
        "workshop", "section", "unit", "fault_category", "fault_subcategory"
    ).order_by("started_at")

    context = {
        "review": review,
        "case": review.case,
        "events": events,
        "case_logs": review.case.logs.select_related("user")[:20],
        "timeline": review.timeline.select_related("author").order_by("occurred_at", "id"),
        "review_logs": review.logs.select_related("user")[:50],
        "transitions": review.available_transitions(),
        "can_manage": can_manage_reviews(request.user),
        "can_edit": can_edit_review(request.user, review),
    }
    return render(request, "reviews/card.html", context)


@login_required
@role_required(*REVIEW_ROLES)
def review_create(request):
    """Создаёт разбор из выбранных простоев (переход из списка «Простои»)."""
    if request.method != "POST":
        return redirect("downtimes:list")

    ids = request.POST.getlist("events")
    events = list(DowntimeEvent.objects.filter(pk__in=ids).select_related("case"))
    if not events:
        messages.error(request, "Выберите хотя бы один простой для разбора.")
        return redirect("downtimes:list")

    lead = _resolve_lead(request)
    title = (request.POST.get("title") or "").strip()
    review, created = create_review_from_events(
        events, lead=lead, created_by=request.user, title=title
    )

    if created:
        messages.success(
            request,
            f"Разбор {review.number} создан. Простоев в инциденте: {review.events.count()}.",
        )
    else:
        messages.info(
            request,
            f"По этому инциденту уже есть разбор {review.number} — открываем его.",
        )
    return redirect("reviews:detail", pk=review.pk)


def _parse_datetime(value):
    """Разбирает значение поля «дата и время» (datetime-local). Пустое/мусор — None."""
    value = (value or "").strip()
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


@login_required
def timeline_add(request, pk):
    """Добавляет запись в хронологию разбора."""
    review = get_object_or_404(IncidentReview, pk=pk)
    if request.method != "POST":
        return redirect("reviews:detail", pk=review.pk)
    if not can_edit_review(request.user, review):
        raise PermissionDenied

    try:
        add_timeline_entry(
            review,
            author=request.user,
            text=request.POST.get("text"),
            occurred_at=_parse_datetime(request.POST.get("occurred_at")),
        )
    except ValueError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Запись добавлена в хронологию.")
    return redirect("reviews:detail", pk=review.pk)


@login_required
def timeline_delete(request, pk, entry_pk):
    """Удаляет запись хронологии."""
    review = get_object_or_404(IncidentReview, pk=pk)
    if request.method != "POST":
        return redirect("reviews:detail", pk=review.pk)
    if not can_edit_review(request.user, review):
        raise PermissionDenied

    entry = get_object_or_404(TimelineEntry, pk=entry_pk, review=review)
    delete_timeline_entry(entry, user=request.user)
    messages.success(request, "Запись удалена.")
    return redirect("reviews:detail", pk=review.pk)


@login_required
def status_change(request, pk):
    """Меняет статус разбора (кнопки переходов)."""
    review = get_object_or_404(IncidentReview, pk=pk)
    if request.method != "POST":
        return redirect("reviews:detail", pk=review.pk)
    if not can_edit_review(request.user, review):
        raise PermissionDenied

    try:
        change_status(review, target=request.POST.get("to"), user=request.user)
    except ValueError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Статус разбора: {review.get_status_display()}.")
    return redirect("reviews:detail", pk=review.pk)
