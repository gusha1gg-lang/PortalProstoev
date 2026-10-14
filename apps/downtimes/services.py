"""
Служебные функции модуля «Простои».

Здесь собраны правила, которые должны работать одинаково везде (админка, импорт, страницы):
- ведение журнала изменений (аудит) — и по простоям, и по кейсам;
- объединение простоев в кейс без двойного счёта;
- поиск похожих записей (кандидатов на объединение).
"""
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from .models import DowntimeCase, DowntimeCaseLog, DowntimeEvent, DowntimeEventLog

# Какие поля простоя отслеживаем в журнале: (имя поля, понятное название).
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
    ("unproduced_tons", "Непроизведённые тонны"),
    ("status", "Статус"),
    ("source", "Источник"),
    ("case", "Кейс"),
]

# Какие поля кейса отслеживаем в журнале.
CASE_TRACKED_FIELDS = [
    ("title", "Название"),
    ("status", "Статус"),
    ("fault_side", "Вина"),
    ("fault_category", "Категория вины"),
    ("fault_subcategory", "Подкатегория вины"),
    ("started_at", "Начало"),
    ("ended_at", "Окончание"),
    ("duration_min", "Длительность, мин"),
    ("unproduced_tons", "Непроизведённые тонны"),
    ("note", "Описание"),
]

# Окно (в минутах), внутри которого записи с одинаковым примечанием считаем дублями.
DUPLICATE_WINDOW_MIN = 120


def _human_value(obj, field):
    """Преобразует значение поля в понятный текст для журнала."""
    display = getattr(obj, f"get_{field}_display", None)
    if callable(display):
        return str(display())
    value = getattr(obj, field)
    if value is None:
        return ""
    if hasattr(value, "pk"):  # объект-справочник (ForeignKey)
        return str(value)
    if hasattr(value, "strftime"):
        local = timezone.localtime(value) if timezone.is_aware(value) else value
        return local.strftime("%d.%m.%Y %H:%M")
    return str(value)


def _snapshot(obj, fields):
    return {label: _human_value(obj, field) for field, label in fields}


def snapshot(event):
    """Снимок отслеживаемых полей простоя."""
    return _snapshot(event, TRACKED_FIELDS)


def case_snapshot(case):
    """Снимок отслеживаемых полей кейса."""
    return _snapshot(case, CASE_TRACKED_FIELDS)


def build_diff(before, after):
    """Разница между двумя снимками: {поле: {было, стало}}."""
    changes = {}
    for label in before:
        if before[label] != after[label]:
            changes[label] = {"было": before[label], "стало": after[label]}
    return changes


# --- Журнал по простоям ---

def log_event(event, user, action, changes=None, comment=""):
    return DowntimeEventLog.objects.create(
        event=event, user=user, action=action, changes=changes or {}, comment=comment
    )


def save_with_audit(event, user=None, comment=""):
    """Сохраняет простой и пишет журнал: создание отдельно, изменение — если есть."""
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


# --- Журнал по кейсам ---

def log_case(case, user, action, changes=None, comment=""):
    return DowntimeCaseLog.objects.create(
        case=case, user=user, action=action, changes=changes or {}, comment=comment
    )


def save_case_with_audit(case, user=None, comment=""):
    """Сохраняет кейс и пишет журнал кейса."""
    is_new = case.pk is None
    before = {} if is_new else case_snapshot(DowntimeCase.objects.get(pk=case.pk))

    case.save()
    after = case_snapshot(case)

    if is_new:
        log_case(case, user, DowntimeCaseLog.Action.CREATED, comment=comment)
        return case

    changes = build_diff(before, after)
    if changes:
        action = (
            DowntimeCaseLog.Action.STATUS
            if "Статус" in changes
            else DowntimeCaseLog.Action.UPDATED
        )
        log_case(case, user, action, changes, comment)
    return case


# --- Расчёт длительности без двойного счёта ---

def union_duration_min(intervals):
    """
    Складывает длительности так, чтобы перекрывающиеся куски считались один раз.

    intervals — список пар (начало, окончание); окончание может быть пустым (None).
    Возвращает минуты (целое).
    """
    closed = sorted((s, e) for s, e in intervals if s and e)
    total = timedelta(0)
    cur_start = cur_end = None
    for start, end in closed:
        if cur_end is None:
            cur_start, cur_end = start, end
        elif start <= cur_end:  # куски перекрываются или стыкуются — склеиваем
            cur_end = max(cur_end, end)
        else:
            total += cur_end - cur_start
            cur_start, cur_end = start, end
    if cur_end is not None:
        total += cur_end - cur_start
    return int(total.total_seconds() // 60)


def recalc_case(case, save=True):
    """Пересчитывает границы и длительность кейса по его событиям."""
    events = list(case.events.all())
    starts = [e.started_at for e in events if e.started_at]
    ends = [e.ended_at for e in events if e.ended_at]

    case.started_at = min(starts) if starts else None
    # Если хоть одно событие ещё идёт — кейс считается незакрытым.
    case.ended_at = None if any(e.ended_at is None for e in events) else (max(ends) if ends else None)
    case.duration_min = union_duration_min([(e.started_at, e.ended_at) for e in events])

    if save:
        case.save()
    return case


# --- Объединение и разъединение ---

def attach_events(case, events, user=None):
    """Привязывает события к кейсу и пересчитывает кейс (без двойного счёта)."""
    events = list(events)
    for event in events:
        if event.case_id != case.id:
            event.case = case
            save_with_audit(event, user)  # в журнале простоя отразится смена кейса
    recalc_case(case)
    log_case(case, user, DowntimeCaseLog.Action.MERGED, {"Событий": len(events)})
    return case


def detach_event(event, user=None):
    """Вынимает событие из кейса и пересчитывает кейс."""
    case = event.case
    if case is None:
        return None
    event.case = None
    save_with_audit(event, user)
    recalc_case(case)
    log_case(case, user, DowntimeCaseLog.Action.UNMERGED, {"Отсоединено": str(event)})
    return case


def create_case_from_events(events, user=None, title="", note="", **extra):
    """Создаёт кейс из набора событий и сразу привязывает их."""
    events = list(events)
    if not events:
        raise ValueError("Нужно хотя бы одно событие для создания кейса.")

    if not title:
        first_note = next((e.note.strip() for e in events if e.note and e.note.strip()), "")
        title = first_note[:255] if first_note else f"Кейс из {len(events)} событий"

    # Классификацию берём с первого события, где она заполнена.
    sample = next((e for e in events if e.fault_category_id), events[0])
    case = DowntimeCase(
        title=title,
        note=note,
        fault_side=sample.fault_side,
        fault_category=sample.fault_category,
        fault_subcategory=sample.fault_subcategory,
        **extra,
    )
    save_case_with_audit(case, user, comment=f"Создан из {len(events)} событий")
    attach_events(case, events, user)
    return case


# --- Поиск дублей ---

def find_duplicate_candidates(window_min=DUPLICATE_WINDOW_MIN):
    """
    Ищет группы похожих простоев (кандидаты на объединение).

    Похожими считаем записи без кейса, у которых одинаковое примечание, одно предприятие
    и начало в пределах `window_min` минут. Возвращает список групп (в каждой 2+ события).
    """
    events = list(
        DowntimeEvent.objects.filter(case__isnull=True)
        .select_related("workshop", "workshop__enterprise", "unit")
        .order_by("started_at")
    )

    grouped = defaultdict(list)
    for event in events:
        note = (event.note or "").strip().lower()
        if not note:
            continue
        grouped[(event.workshop.enterprise_id, note)].append(event)

    groups = []
    for same in grouped.values():
        cluster = []
        for event in same:
            if cluster and (event.started_at - cluster[-1].started_at) <= timedelta(minutes=window_min):
                cluster.append(event)
            else:
                if len(cluster) >= 2:
                    groups.append(cluster)
                cluster = [event]
        if len(cluster) >= 2:
            groups.append(cluster)

    groups.sort(key=lambda group: group[0].started_at)
    return groups
