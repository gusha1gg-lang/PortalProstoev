"""
Страницы модуля «Разбор простоя» (этап 11.7, шаг 1).

Список разборов, карточка разбора и создание разбора из выбранных простоев.
Просмотр — любому вошедшему (как простои и отчёты). Создание и ведение — ролям
«Специалист по простоям», «Руководитель ИТ», «Администратор».
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.decorators import role_required
from apps.downtimes.models import DowntimeEvent

from .models import IncidentReview
from .permissions import REVIEW_ROLES, can_manage_reviews
from .services import create_review_from_events, eligible_leads

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
        "can_manage": can_manage_reviews(request.user),
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
