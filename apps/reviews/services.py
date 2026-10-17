"""
Служебные функции модуля «Разбор простоя».

- `create_review_from_events` — из одного или нескольких простоев создаёт разбор
  (несколько простоев объединяет в инцидент, чтобы не было двойного счёта);
- `add_timeline_entry` / `delete_timeline_entry` — хронология разбора;
- `change_status` — смена статуса разбора с проверкой допустимых переходов.

Логику объединения не дублируем: используем проверенные функции модуля «Простои».
"""
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.downtimes.services import create_case_from_events

from .models import STATUS_TRANSITIONS, IncidentReview, ReviewLog, TimelineEntry


def eligible_leads():
    """Пользователи, которых можно назначить ведущим разбора (по ролям)."""
    from .permissions import REVIEW_ROLES

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