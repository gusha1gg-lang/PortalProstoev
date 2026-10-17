"""
Служебные функции модуля «Разбор простоя».

Главная из них — `create_review_from_events`: из одного или нескольких простоев
создаёт разбор. Если простоев несколько (или они ещё не собраны в инцидент), сначала
объединяем их в инцидент (`DowntimeCase`) — так сохраняется «один инцидент = один случай,
без двойного счёта». Если разбор для этого инцидента уже есть — возвращаем его.

Логику объединения не дублируем: используем проверенные функции модуля «Простои».
"""
from apps.downtimes.services import create_case_from_events

from .models import IncidentReview
from .permissions import REVIEW_ROLES


def eligible_leads():
    """Пользователи, которых можно назначить ведущим разбора (по ролям)."""
    from django.contrib.auth import get_user_model

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

    return IncidentReview.objects.get_or_create(
        case=case,
        defaults={
            "lead": lead,
            "created_by": created_by,
            "title": title or case.title,
        },
    )
