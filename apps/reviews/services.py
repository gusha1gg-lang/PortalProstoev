"""
Служебные функции модуля «Разбор простоя».

- `create_review_from_events` — из одного или нескольких простоев создаёт разбор
  (несколько простоев объединяет в инцидент, чтобы не было двойного счёта);
- `add_timeline_entry` / `delete_timeline_entry` — хронология разбора;
- `change_status` — смена статуса разбора с проверкой допустимых переходов.

Логику объединения не дублируем: используем проверенные функции модуля «Простои».
"""
import re

from django.contrib.auth import get_user_model
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.downtimes.services import create_case_from_events
from apps.notifications.services import notify_review_mention

from .models import (
    STATUS_TRANSITIONS,
    ActionTemplate,
    IncidentReview,
    ReviewAction,
    ReviewLog,
    ReviewMessage,
    ReviewParticipant,
    TimelineEntry,
)
from .permissions import REVIEW_ROLES

# Как выглядит упоминание в тексте: @логин. Логин может содержать буквы, цифры и . @ + - _.
MENTION_RE = re.compile(r"@([\w.@+-]+)")


def eligible_leads():
    """Пользователи, которых можно назначить ведущим разбора (по ролям)."""
    return (
        get_user_model()
        .objects.filter(groups__name__in=REVIEW_ROLES)
        .distinct()
        .order_by("username")
    )


def create_review_from_events(events, lead, created_by, title=""):
    """Создаёт разбор из простоев. Возвращает пару (разбор, создан_ли_новый)."""
    events = list(events)
    if not events:
        raise ValueError("Нужен хотя бы один простой для разбора.")

    # Если все простои уже в одном инциденте — берём его; иначе объединяем в новый.
    case_ids = {event.case_id for event in events}
    if len(case_ids) == 1 and None not in case_ids:
        case = events[0].case
    else:
        case = create_case_from_events(events, user=created_by)

    review, created = IncidentReview.objects.get_or_create(
        case=case,
        defaults={
            "lead": lead,
            "created_by": created_by,
            "title": title or case.title,
        },
    )
    if created:
        ReviewLog.objects.create(
            review=review,
            user=created_by,
            action=ReviewLog.Action.CREATED,
            comment=f"Разбор создан из {len(events)} простоев, ведущий {lead.username}",
        )
    return review, created


def add_timeline_entry(review, author, text, occurred_at=None):
    """Добавляет запись в хронологию разбора."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Запись хронологии не может быть пустой.")
    entry = TimelineEntry.objects.create(
        review=review,
        author=author,
        text=text,
        occurred_at=occurred_at or timezone.now(),
    )
    ReviewLog.objects.create(
        review=review, user=author, action=ReviewLog.Action.UPDATED,
        comment="Добавлена запись хронологии",
    )
    return entry


def delete_timeline_entry(entry, user):
    """Удаляет запись хронологии и отмечает это в истории разбора."""
    ReviewLog.objects.create(
        review=entry.review, user=user, action=ReviewLog.Action.UPDATED,
        comment="Удалена запись хронологии",
    )
    entry.delete()


def change_status(review, target, user):
    """Меняет статус разбора, если переход разрешён. Возвращает (старый, новый) названия."""
    allowed = {t for (source, t) in STATUS_TRANSITIONS if source == review.status}
    if target not in allowed:
        raise ValueError("Такой переход статуса недопустим.")

    old = review.get_status_display()
    review.status = target
    review.save(update_fields=["status", "updated_at"])
    ReviewLog.objects.create(
        review=review,
        user=user,
        action=ReviewLog.Action.STATUS,
        comment=f"{old} → {review.get_status_display()}",
    )
    return old, review.get_status_display()


# --- Участники ---

def add_participant(review, user, is_approver=False, by=None):
    """Добавляет участника в разбор. Возвращает пару (участник, создан_ли_новый)."""
    participant, created = ReviewParticipant.objects.get_or_create(
        review=review, user=user, defaults={"is_approver": is_approver}
    )
    if created:
        ReviewLog.objects.create(
            review=review,
            user=by,
            action=ReviewLog.Action.UPDATED,
            comment=f"Добавлен участник {user.get_username()}",
        )
    return participant, created


def remove_participant(review, user, by=None):
    """Убирает участника из разбора. Возвращает True, если участник был."""
    deleted, _ = ReviewParticipant.objects.filter(review=review, user=user).delete()
    if deleted:
        ReviewLog.objects.create(
            review=review,
            user=by,
            action=ReviewLog.Action.UPDATED,
            comment=f"Удалён участник {user.get_username()}",
        )
    return bool(deleted)


# --- Чат и упоминания ---

def extract_mentions(text):
    """Возвращает список логинов, упомянутых через @ (без повторов, в порядке появления)."""
    seen = []
    for login in MENTION_RE.findall(text or ""):
        if login not in seen:
            seen.append(login)
    return seen


def post_review_message(review, author, text, request=None):
    """Пишет сообщение в чат разбора.

    Упомянутых (`@логин`) автоматически делаем участниками и шлём им письмо
    «вас упомянули…». Возвращает сообщение.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Сообщение не может быть пустым.")

    message = ReviewMessage.objects.create(review=review, author=author, text=text)

    usernames = MENTION_RE.findall(text)
    if usernames:
        mentioned = list(
            get_user_model().objects.filter(username__in=set(usernames)).distinct()
        )
        message.mentions.set(mentioned)

        url = ""
        if request is not None:
            try:
                url = request.build_absolute_uri(reverse("reviews:detail", args=[review.pk]))
            except Exception:  # noqa: BLE001 — ссылка не критична для письма
                url = ""

        for user in mentioned:
            if user.pk == getattr(author, "pk", None):
                continue  # себя не приглашаем и не уведомляем
            add_participant(review, user, by=author)
            notify_review_mention(review, text, user, author=author, url=url)
    return message


def remove_message(message, user):
    """Удаляет сообщение чата и отмечает это в истории разбора."""
    ReviewLog.objects.create(
        review=message.review, user=user, action=ReviewLog.Action.UPDATED,
        comment="Удалено сообщение чата",
    )
    message.delete()

# --- Шаблоны мероприятий ---

def active_templates_for(category):
    """Активные шаблоны мероприятий для ситуации: общие + под нужную категорию вины."""
    query = models.Q(category__isnull=True)
    if category is not None:
        query |= models.Q(category=category)
    return ActionTemplate.objects.filter(is_active=True).filter(query).order_by("order", "title")


# --- Мероприятия ---

def add_review_action(review, created_by, title="", description="", due_at=None,
                      assignees=None, template=None):
    """Добавляет мероприятие в разбор.

    Если выбран `template` и название не заполнено — берём название и описание из шаблона.
    Ответственных автоматически делаем участниками разбора (чтобы видели разбор).
    """
    title = (title or "").strip()
    description = (description or "").strip()
    if template is not None:
        if not title:
            title = template.title
        if not description:
            description = template.description
    if not title:
        raise ValueError("У мероприятия должно быть название.")

    action = ReviewAction.objects.create(
        review=review,
        created_by=created_by,
        title=title,
        description=description,
        due_at=due_at,
    )
    assignees = list(assignees or [])
    if assignees:
        action.assignees.set(assignees)
        for user in assignees:
            add_participant(review, user, by=created_by)

    ReviewLog.objects.create(
        review=review, user=created_by, action=ReviewLog.Action.UPDATED,
        comment=f"Добавлено мероприятие «{title}»",
    )
    return action


def update_review_action(action, user, title, description="", due_at=None, assignees=None):
    """Меняет мероприятие: название, описание, срок, ответственных."""
    title = (title or "").strip()
    if not title:
        raise ValueError("У мероприятия должно быть название.")

    action.title = title
    action.description = (description or "").strip()
    action.due_at = due_at
    action.save(update_fields=["title", "description", "due_at", "updated_at"])

    assignees = list(assignees or [])
    action.assignees.set(assignees)
    for user in assignees:
        add_participant(action.review, user, by=user)

    ReviewLog.objects.create(
        review=action.review, user=user, action=ReviewLog.Action.UPDATED,
        comment=f"Изменено мероприятие «{title}»",
    )
    return action


def set_action_status(action, target, user):
    """Меняет статус мероприятия (вручную). Возвращает названия старого и нового статусов."""
    allowed = {value for value, _label in ReviewAction.Status.choices}
    if target not in allowed:
        raise ValueError("Неизвестный статус мероприятия.")
    old = action.get_status_display()
    action.status = target
    action.save(update_fields=["status", "updated_at"])
    ReviewLog.objects.create(
        review=action.review, user=user, action=ReviewLog.Action.UPDATED,
        comment=f"Мероприятие «{action.title}»: {old} → {action.get_status_display()}",
    )
    return old, action.get_status_display()


def delete_review_action(action, user):
    """Удаляет мероприятие и отмечает это в истории разбора."""
    review = action.review
    title = action.title
    action.delete()
    ReviewLog.objects.create(
        review=review, user=user, action=ReviewLog.Action.UPDATED,
        comment=f"Удалено мероприятие «{title}»",
    )
