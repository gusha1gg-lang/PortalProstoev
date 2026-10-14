"""
Служебные функции модуля «Простои».

Главная задача — вести журнал изменений (аудит) единообразно: где бы мы ни сохраняли
простой (админка, импорт из Oracle, будущие страницы), пишем одну и ту же запись в журнал.
"""
from django.utils import timezone

from .models import DowntimeEvent, DowntimeEventLog

# Какие поля отслеживаем в журнале: (имя поля, понятное название).
TRACKED_FIELDS = [
    ("started_at", "Начало"),
    ("ended_at", "Окончание"),
    ("workshop", "Цех"),
    ("section", "Участок"),
    ("unit", "Агрегат"),
    ("service", "Служба"),
    ("fault_side", "Вина"),
    ("fault_category", "Категория вины"),
    ("fault_subcategory", "Подкатегория вины"),
    ("note", "Примечание"),
    ("recorded_by_name", "Кто зафиксировал"),
    ("status", "Статус"),
    ("source", "Источник"),
]


def _human_value(event, field):
    """Преобразует значение поля в понятный текст для журнала."""
    display = getattr(event, f"get_{field}_display", None)
    if callable(display):
        return str(display())
    value = getattr(event, field)
    if value is None:
        return ""
    if hasattr(value, "pk"):  # объект-справочник (ForeignKey)
        return str(value)
    if hasattr(value, "strftime"):
        local = timezone.localtime(value) if timezone.is_aware(value) else value
        return local.strftime("%d.%m.%Y %H:%M")
    return str(value)


def snapshot(event):
    """Снимок отслеживаемых полей: {понятное название: значение}."""
    return {label: _human_value(event, field) for field, label in TRACKED_FIELDS}


def build_diff(before, after):
    """Разница между двумя снимками: {поле: {было, стало}}."""
    changes = {}
    for label in before:
        if before[label] != after[label]:
            changes[label] = {"было": before[label], "стало": after[label]}
    return changes


def log_event(event, user, action, changes=None, comment=""):
    """Пишем строку в журнал изменений."""
    return DowntimeEventLog.objects.create(
        event=event,
        user=user,
        action=action,
        changes=changes or {},
        comment=comment,
    )


def save_with_audit(event, user=None, comment=""):
    """
    Сохраняет простой и автоматически пишет журнал:
    создание — отдельной записью, изменение — только если что-то поменялось.
    """
    is_new = event.pk is None
    before = {} if is_new else snapshot(DowntimeEvent.objects.get(pk=event.pk))

    event.save()
    after = snapshot(event)

    if is_new:
        log_event(event, user, DowntimeEventLog.Action.CREATED, comment=comment)
        return event

    changes = build_diff(before, after)
    if changes:
        action = (
            DowntimeEventLog.Action.STATUS
            if "Статус" in changes
            else DowntimeEventLog.Action.UPDATED
        )
        log_event(event, user, action, changes, comment)
    return event
