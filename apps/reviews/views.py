"""
Страницы модуля «Разбор простоя» (этап 11.7).

Список разборов, карточка разбора, создание разбора из выбранных простоев,
хронология и статусы, участники и чат с упоминаниями (`@логин` → письмо).

Видеть разбор может ведущий, автор, участники и роли `REVIEW_ROLES`; вести
содержание (хронология, чат) — роли, ведущий и участники; управлять (статус,
участники) — роли и ведущий.
"""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.html import escape
from django.utils.safestring import mark_safe

from apps.accounts.decorators import role_required
from apps.catalog.models import ItFaultCategory
from apps.downtimes.models import DowntimeEvent

from .models import ActionTemplate, IncidentReview, ReviewAction, ReviewApproval
from .permissions import (
    REVIEW_ROLES,
    can_edit_review,
    can_manage_review,
    can_manage_reviews,
    can_view_review,
    visible_reviews,
)
from .services import (
    MENTION_RE,
    active_templates_for,
    add_participant,
    add_review_action,
    add_timeline_entry,
    approve,
    change_status,
    create_review_from_events,
    delete_review_action,
    delete_timeline_entry,
    eligible_leads,
    post_review_message,
    reject,
    remove_message,
    remove_participant,
    set_action_status,
    set_approver,
    update_review_action,
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


def _render_message(text):
    """Экранирует текст сообщения и подсвечивает упоминания `@логин`."""
    safe = escape(text or "")
    return mark_safe(MENTION_RE.sub(r'<span class="mention">@\1</span>', safe))


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


def _category_from_post(request):
    """Категория вины из формы (или None — «общий шаблон»)."""
    category_id = (request.POST.get("category") or "").strip()
    if category_id.isdigit():
        return ItFaultCategory.objects.filter(pk=category_id).first()
    return None


def _int_or_default(value, default):
    """Целое из формы; не число — берём значение по умолчанию."""
    value = (value or "").strip()
    return int(value) if value.isdigit() else default


@login_required
def review_list(request):
    """Список разборов, видимых пользователю, с фильтрами."""
    reviews = (
        visible_reviews(request.user)
        .select_related("case", "lead")
        .order_by("-created_at")
    )

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
    """Карточка разбора: шапка, входящие простои, хронология, чат, участники, история."""
    review = get_object_or_404(
        IncidentReview.objects.select_related("case", "lead", "created_by"), pk=pk
    )
    if not can_view_review(request.user, review):
        raise PermissionDenied

    events = review.events.select_related(
        "workshop", "section", "unit", "fault_category", "fault_subcategory"
    ).order_by("started_at")

    chat = [
        {"message": message, "html": _render_message(message.text)}
        for message in review.messages.select_related("author").prefetch_related("mentions")
    ]

    actions = list(
        review.actions.select_related("created_by").prefetch_related("assignees")
    )
    actions_done = sum(1 for a in actions if a.status == ReviewAction.Status.DONE)

    context = {
        "review": review,
        "case": review.case,
        "events": events,
        "case_logs": review.case.logs.select_related("user")[:20],
        "timeline": review.timeline.select_related("author").order_by("occurred_at", "id"),
        "chat": chat,
        "actions": actions,
        "actions_done": actions_done,
        "action_statuses": ReviewAction.Status.choices,
        "templates": active_templates_for(review.case.fault_category),
        "review_logs": review.logs.select_related("user")[:50],
        "participants": review.participants.select_related("user"),
        "approvals": review.approvals.select_related("user"),
        "my_approval": review.approvals.filter(user=request.user).first(),
        "can_approve": can_edit_review(request.user, review)
        and review.status == IncidentReview.Status.ON_APPROVAL
        and review.participants.filter(user=request.user, is_approver=True).exists(),
        "all_users": get_user_model().objects.filter(is_active=True).order_by("username"),
        "transitions": review.available_transitions(),
        "can_manage": can_manage_reviews(request.user),
        "can_edit": can_edit_review(request.user, review),
        "can_manage_this": can_manage_review(request.user, review),
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

    entry = get_object_or_404(review.timeline, pk=entry_pk)
    delete_timeline_entry(entry, user=request.user)
    messages.success(request, "Запись удалена.")
    return redirect("reviews:detail", pk=review.pk)


@login_required
def status_change(request, pk):
    """Меняет статус разбора (кнопки переходов)."""
    review = get_object_or_404(IncidentReview, pk=pk)
    if request.method != "POST":
        return redirect("reviews:detail", pk=review.pk)
    if not can_manage_review(request.user, review):
        raise PermissionDenied

    try:
        change_status(review, target=request.POST.get("to"), user=request.user)
    except ValueError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Статус разбора: {review.get_status_display()}.")
    return redirect("reviews:detail", pk=review.pk)


@login_required
def message_add(request, pk):
    """Добавляет сообщение в чат разбора (упоминания `@логин` → письмо)."""
    review = get_object_or_404(IncidentReview, pk=pk)
    if request.method != "POST":
        return redirect("reviews:detail", pk=review.pk)
    if not can_edit_review(request.user, review):
        raise PermissionDenied

    try:
        post_review_message(review, author=request.user, text=request.POST.get("text"),
                            request=request)
    except ValueError as error:
        messages.error(request, str(error))
    return redirect("reviews:detail", pk=review.pk)


@login_required
def message_delete(request, pk, message_pk):
    """Удаляет сообщение чата (роли и ведущий)."""
    review = get_object_or_404(IncidentReview, pk=pk)
    if request.method != "POST":
        return redirect("reviews:detail", pk=review.pk)
    if not can_manage_review(request.user, review):
        raise PermissionDenied

    message = get_object_or_404(review.messages, pk=message_pk)
    remove_message(message, user=request.user)
    messages.success(request, "Сообщение удалено.")
    return redirect("reviews:detail", pk=review.pk)


@login_required
def participant_add(request, pk):
    """Добавляет участника в разбор."""
    review = get_object_or_404(IncidentReview, pk=pk)
    if request.method != "POST":
        return redirect("reviews:detail", pk=review.pk)
    if not can_manage_review(request.user, review):
        raise PermissionDenied

    user_id = (request.POST.get("user") or "").strip()
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first() if user_id.isdigit() else None
    if user is None:
        messages.error(request, "Выберите пользователя.")
    else:
        _, created = add_participant(review, user, by=request.user)
        if created:
            messages.success(request, f"Участник {user.username} добавлен.")
        else:
            messages.info(request, f"{user.username} уже участвует в разборе.")
    return redirect("reviews:detail", pk=review.pk)


@login_required
def participant_remove(request, pk, user_pk):
    """Убирает участника из разбора."""
    review = get_object_or_404(IncidentReview, pk=pk)
    if request.method != "POST":
        return redirect("reviews:detail", pk=review.pk)
    if not can_manage_review(request.user, review):
        raise PermissionDenied

    user = get_user_model().objects.filter(pk=user_pk).first()
    if user is not None:
        remove_participant(review, user, by=request.user)
        messages.success(request, f"Участник {user.username} убран.")
    return redirect("reviews:detail", pk=review.pk)


# --- Мероприятия ---

def _parse_assignees(request):
    """Выбранные ответственные (несколько) из формы мероприятия."""
    ids = [value for value in request.POST.getlist("assignees") if value.isdigit()]
    return list(get_user_model().objects.filter(pk__in=ids))


def _template_from_post(request):
    """Шаблон мероприятия, выбранный в форме (если есть и активен)."""
    template_id = (request.POST.get("template") or "").strip()
    if template_id.isdigit():
        return ActionTemplate.objects.filter(pk=template_id, is_active=True).first()
    return None


@login_required
def action_add(request, pk):
    """Добавляет мероприятие в разбор."""
    review = get_object_or_404(IncidentReview, pk=pk)
    if request.method != "POST":
        return redirect("reviews:detail", pk=review.pk)
    if not can_edit_review(request.user, review):
        raise PermissionDenied

    try:
        add_review_action(
            review,
            created_by=request.user,
            title=request.POST.get("title"),
            description=request.POST.get("description"),
            due_at=_parse_datetime(request.POST.get("due_at")),
            assignees=_parse_assignees(request),
            template=_template_from_post(request),
        )
    except ValueError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Мероприятие добавлено.")
    return redirect("reviews:detail", pk=review.pk)


@login_required
def action_edit(request, pk, action_pk):
    """Правка мероприятия: название, описание, срок, ответственные."""
    review = get_object_or_404(IncidentReview, pk=pk)
    action = get_object_or_404(review.actions, pk=action_pk)
    if not can_edit_review(request.user, review):
        raise PermissionDenied

    if request.method == "POST":
        try:
            update_review_action(
                action,
                user=request.user,
                title=request.POST.get("title"),
                description=request.POST.get("description"),
                due_at=_parse_datetime(request.POST.get("due_at")),
                assignees=_parse_assignees(request),
            )
        except ValueError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "Мероприятие сохранено.")
            return redirect("reviews:detail", pk=review.pk)

    context = {
        "review": review,
        "action": action,
        "all_users": get_user_model().objects.filter(is_active=True).order_by("username"),
        "assignee_ids": set(action.assignees.values_list("pk", flat=True)),
    }
    return render(request, "reviews/action_form.html", context)


@login_required
def action_status(request, pk, action_pk):
    """Меняет статус мероприятия вручную."""
    review = get_object_or_404(IncidentReview, pk=pk)
    if request.method != "POST":
        return redirect("reviews:detail", pk=review.pk)
    if not can_edit_review(request.user, review):
        raise PermissionDenied

    action = get_object_or_404(review.actions, pk=action_pk)
    try:
        set_action_status(action, target=request.POST.get("to"), user=request.user)
    except ValueError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Мероприятие: {action.get_status_display()}.")
    return redirect("reviews:detail", pk=review.pk)


@login_required
def action_delete(request, pk, action_pk):
    """Удаляет мероприятие (роли и ведущий)."""
    review = get_object_or_404(IncidentReview, pk=pk)
    if request.method != "POST":
        return redirect("reviews:detail", pk=review.pk)
    if not can_manage_review(request.user, review):
        raise PermissionDenied

    action = get_object_or_404(review.actions, pk=action_pk)
    delete_review_action(action, user=request.user)
    messages.success(request, "Мероприятие удалено.")
    return redirect("reviews:detail", pk=review.pk)


# --- Шаблоны мероприятий (справочник) ---

@login_required
@role_required(*REVIEW_ROLES)
def template_list(request):
    """Список шаблонов мероприятий по ситуациям (скрытые — тоже видны)."""
    context = {
        "templates": ActionTemplate.objects.select_related("category"),
        "categories": ItFaultCategory.objects.filter(is_active=True).order_by("name"),
    }
    return render(request, "reviews/templates.html", context)


@login_required
@role_required(*REVIEW_ROLES)
def template_add(request):
    """Добавляет шаблон мероприятия."""
    if request.method != "POST":
        return redirect("reviews:templates")

    title = (request.POST.get("title") or "").strip()
    if not title:
        messages.error(request, "У шаблона должно быть название.")
        return redirect("reviews:templates")

    category = _category_from_post(request)
    ActionTemplate.objects.create(
        title=title,
        description=(request.POST.get("description") or "").strip(),
        category=category,
        order=_int_or_default(request.POST.get("order"), 100),
    )
    messages.success(request, "Шаблон добавлен.")
    return redirect("reviews:templates")


@login_required
@role_required(*REVIEW_ROLES)
def template_edit(request, pk):
    """Правка шаблона мероприятия."""
    template = get_object_or_404(ActionTemplate, pk=pk)
    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "У шаблона должно быть название.")
        else:
            template.title = title
            template.description = (request.POST.get("description") or "").strip()
            category_id = (request.POST.get("category") or "").strip()
            template.category = (
                ItFaultCategory.objects.filter(pk=category_id).first()
                if category_id.isdigit()
                else None
            )
            order = (request.POST.get("order") or "").strip()
            if order.isdigit():
                template.order = int(order)
            template.save()
            messages.success(request, "Шаблон сохранён.")
            return redirect("reviews:templates")

    context = {
        "template": template,
        "categories": ItFaultCategory.objects.filter(is_active=True).order_by("name"),
    }
    return render(request, "reviews/template_form.html", context)


@login_required
@role_required(*REVIEW_ROLES)
def template_toggle(request, pk):
    """Скрывает или возвращает шаблон (не удаляем — как в справочниках)."""
    template = get_object_or_404(ActionTemplate, pk=pk)
    if request.method == "POST":
        ActionTemplate.objects.filter(pk=template.pk).update(is_active=not template.is_active)
        messages.success(
            request,
            "Шаблон скрыт." if template.is_active else "Шаблон возвращён.",
        )
    return redirect("reviews:templates")


# --- Согласование ---

@login_required
def approval_decide(request, pk):
    """Согласующий согласует разбор или возвращает его на доработку."""
    review = get_object_or_404(IncidentReview, pk=pk)
    if request.method != "POST":
        return redirect("reviews:detail", pk=review.pk)
    if not can_edit_review(request.user, review):
        raise PermissionDenied
    if not review.participants.filter(user=request.user, is_approver=True).exists():
        raise PermissionDenied

    decision = (request.POST.get("decision") or "").strip()
    comment = request.POST.get("comment")
    try:
        if decision == "approve":
            approve(review, user=request.user, comment=comment)
            messages.success(request, "Разбор согласован.")
        elif decision == "reject":
            reject(review, user=request.user, comment=comment)
            messages.success(request, "Разбор возвращён на доработку.")
        else:
            raise ValueError("Неизвестное решение по согласованию.")
    except ValueError as error:
        messages.error(request, str(error))
    return redirect("reviews:detail", pk=review.pk)


@login_required
def approver_toggle(request, pk, user_pk):
    """Назначает участника согласующим или снимает его (роли и ведущий)."""
    review = get_object_or_404(IncidentReview, pk=pk)
    if request.method != "POST":
        return redirect("reviews:detail", pk=review.pk)
    if not can_manage_review(request.user, review):
        raise PermissionDenied

    user = get_object_or_404(get_user_model(), pk=user_pk)
    is_approver = request.POST.get("value") == "on"
    set_approver(review, user, is_approver, by=request.user)
    messages.success(
        request,
        f"{user.get_username()}: "
        + ("назначен согласующим." if is_approver else "снят с согласования."),
    )
    return redirect("reviews:detail", pk=review.pk)
