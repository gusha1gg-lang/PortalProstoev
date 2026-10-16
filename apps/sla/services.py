"""
Расчёты модуля «Потери и SLA» — в одном месте, чтобы админка, страницы и отчёты
считали одинаково.

Простыми словами:
    потери = часы × ставка_участка.

Непроизведённые тонны хранятся и показываются справочно, но в деньгах не участвуют.

Для кейса (несколько дублей) время по каждому участку берётся БЕЗ двойного счёта:
сначала объединяются интервалы событий одного участка, потом умножается на его ставку.
Результат суммируется по участкам.

Ставки версионируются по датам — берём ставку, действовавшую на дату простоя.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from apps.catalog.models import LossRate, Section
from apps.downtimes.models import DowntimeEvent
from apps.downtimes.services import union_duration_min

from .models import SlaContract

# Статусы, при которых простой считаем состоявшимся (учитываем в потерях и SLA).
INCIDENT_STATUSES = (DowntimeEvent.Status.CONFIRMED, DowntimeEvent.Status.CLOSED)

MONEY = Decimal("0.01")


# --- Результаты расчёта (чтобы было понятно, из чего сложилась сумма) ---

@dataclass
class LossLine:
    """Одна строка расчёта: участок, время, тонны, ставка и сумма."""

    section: Section | None
    minutes: int
    tons: Decimal
    rate: LossRate | None
    amount: Decimal


@dataclass
class Loss:
    """Итог расчёта потерь по одному инциденту (простою или кейсу)."""

    minutes: int  # «чистое» время инцидента
    amount: Decimal  # потери в рублях
    tons: Decimal  # непроизведённые тонны
    lines: list[LossLine] = field(default_factory=list)
    missing_rate: bool = False  # где-то не нашлась ставка (участок не указан или ставка не заведена)

    @property
    def hours(self) -> Decimal:
        return (Decimal(self.minutes) / Decimal(60)).quantize(Decimal("0.001"))


def _tons(value) -> Decimal:
    """Аккуратно приводит тонны к Decimal (пустое значение = 0)."""
    return Decimal(value or 0)


def rate_for(section, on_date):
    """Ставка потерь по участку, действовавшая на указанную дату (или None)."""
    if section is None:
        return None
    return (
        LossRate.objects.filter(section=section, valid_from__lte=on_date)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=on_date))
        .order_by("-valid_from")
        .first()
    )


def _date_of(value):
    """Локальная дата события (для подбора ставки)."""
    if value is None:
        return timezone.localdate()
    if timezone.is_aware(value):
        return timezone.localtime(value).date()
    return value.date()


def event_loss(event: DowntimeEvent) -> Loss:
    """Потери по одиночному простою."""
    on_date = _date_of(event.started_at)
    rate = rate_for(event.section, on_date)
    tons = _tons(event.unproduced_tons)

    amount = Decimal("0")
    if rate is not None:
        hours = Decimal(event.duration_min) / Decimal(60)
        amount = (hours * rate.cost_per_hour).quantize(MONEY)

    line = LossLine(section=event.section, minutes=event.duration_min, tons=tons, rate=rate, amount=amount)
    return Loss(
        minutes=event.duration_min,
        amount=amount,
        tons=tons,
        lines=[line],
        missing_rate=rate is None,
    )


def case_loss(case) -> Loss:
    """Потери по кейсу: по каждому участку — объединённое время, затем сумма по участкам."""
    events = list(case.events.all())
    on_date = _date_of(case.started_at)

    # Группируем события по участку (участок = None — отдельная «проблемная» группа).
    grouped = defaultdict(list)
    for event in events:
        grouped[event.section_id].append(event)

    sections = {s.id: s for s in Section.objects.filter(id__in=[sid for sid in grouped if sid])}

    lines = []
    total_amount = Decimal("0")
    total_tons = Decimal("0")
    missing = False

    for section_id, section_events in grouped.items():
        section = sections.get(section_id)
        rate = rate_for(section, on_date)
        # Время участка без двойного счёта: перекрывающиеся записи считаются один раз.
        minutes = union_duration_min([(e.started_at, e.ended_at) for e in section_events])
        tons = sum((_tons(e.unproduced_tons) for e in section_events), Decimal("0"))

        if rate is not None:
            hours = Decimal(minutes) / Decimal(60)
            amount = (hours * rate.cost_per_hour).quantize(MONEY)
        else:
            amount = Decimal("0")
            missing = True

        lines.append(LossLine(section=section, minutes=minutes, tons=tons, rate=rate, amount=amount))
        total_amount += amount
        total_tons += tons

    # Тонны, заданные на карточке кейса, относим на участок с наибольшим временем — только справочно.
    case_tons = _tons(case.unproduced_tons)
    if case_tons and lines:
        primary = max(lines, key=lambda line: line.minutes)
        primary.tons += case_tons
        total_tons += case_tons

    return Loss(
        minutes=case.duration_min,
        amount=total_amount.quantize(MONEY),
        tons=total_tons,
        lines=lines,
        missing_rate=missing,
    )


# --- SLA: период, договоры, сводка ---

def contract_for(workshop, on_date):
    """Договор SLA для цеха, действовавший на указанную дату.

    Сначала ищем договор, привязанный именно к цеху; если такого нет — берём общий
    (без цеха).
    """
    base = SlaContract.objects.filter(
        is_active=True, valid_from__lte=on_date
    ).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=on_date))
    if workshop is not None:
        specific = base.filter(workshop=workshop).order_by("-valid_from").first()
        if specific is not None:
            return specific
    return base.filter(workshop__isnull=True).order_by("-valid_from").first()


def period_bounds(year: int, month: int):
    """Границы месяца: [начало, начало следующего месяца)."""
    start = timezone.make_aware(datetime(year, month, 1))
    if month == 12:
        end = timezone.make_aware(datetime(year + 1, 1, 1))
    else:
        end = timezone.make_aware(datetime(year, month + 1, 1))
    return start, end


def incidents_for(workshop, start, end, it_only=True):
    """
    Инциденты цеха за период: кейсы (по одному на кейс) и одиночные простои.

    Учитываем статусы «Подтверждён»/«Закрыт». При it_only=True — только вину ИТ
    (так считаются потери и SLA); при it_only=False — все службы (нужно для показателя
    «доля простоев по вине ИТ»).
    """
    filters = {
        "workshop": workshop,
        "status__in": INCIDENT_STATUSES,
        "started_at__gte": start,
        "started_at__lt": end,
    }
    if it_only:
        filters["fault_side"] = DowntimeEvent.FaultSide.IT

    events = list(
        DowntimeEvent.objects.filter(**filters)
        .select_related("section", "case", "fault_category", "workshop")
        .order_by("started_at")
    )

    incidents = []
    seen_cases = set()
    for event in events:
        if event.case_id:
            if event.case_id in seen_cases:
                continue  # кейс учитываем один раз
            seen_cases.add(event.case_id)
            case = event.case
            category = case.fault_category.name if case.fault_category else ""
            incidents.append(
                {
                    "kind": "case",
                    "title": str(case),
                    "when": case.started_at,
                    "duration_min": case.duration_min,
                    "loss": case_loss(case),
                    "category": category or "Без категории",
                    "side": case.get_fault_side_display(),
                    "workshop": workshop.name,
                }
            )
        else:
            category = event.fault_category.name if event.fault_category else ""
            incidents.append(
                {
                    "kind": "event",
                    "title": event.note or f"Простой · {event.workshop.name}",
                    "when": event.started_at,
                    "duration_min": event.duration_min,
                    "loss": event_loss(event),
                    "category": category or "Без категории",
                    "side": event.get_fault_side_display(),
                    "workshop": workshop.name,
                }
            )
    return incidents


def sla_summary(workshop, year: int, month: int) -> dict:
    """Сводка по цеху за месяц: потери, доступность, MTTR/MTBF, штраф."""
    start, end = period_bounds(year, month)
    period_min = int((end - start).total_seconds() // 60)

    incidents = incidents_for(workshop, start, end)
    downtime_min = sum(i["duration_min"] for i in incidents)
    count = len(incidents)

    total_loss = sum((i["loss"].amount for i in incidents), Decimal("0"))
    missing = any(i["loss"].missing_rate for i in incidents)

    if period_min:
        availability = Decimal(period_min - downtime_min) / Decimal(period_min) * 100
    else:
        availability = Decimal("100")

    mttr = Decimal(downtime_min) / Decimal(count) if count else Decimal("0")
    mtbf = Decimal(period_min - downtime_min) / Decimal(count) if count else Decimal("0")

    contract = contract_for(workshop, start.date())
    penalty = Decimal("0")
    allowed_min = None
    if contract is not None:
        # Разрешённый простой = время периода × (1 − целевая доступность).
        allowed_min = Decimal(period_min) * (Decimal(1) - contract.target_availability / Decimal(100))
        over = Decimal(downtime_min) - allowed_min
        if over > 0:
            penalty = (over / Decimal(60) * contract.penalty_per_hour).quantize(MONEY)

    return {
        "workshop": workshop,
        "period_min": period_min,
        "incidents": incidents,
        "incident_count": count,
        "downtime_min": downtime_min,
        "availability": availability.quantize(MONEY),
        "mttr_min": mttr.quantize(Decimal("0.1")),
        "mtbf_min": mtbf.quantize(Decimal("0.1")),
        "total_loss": total_loss.quantize(MONEY),
        "missing_rate": missing,
        "contract": contract,
        "allowed_min": allowed_min,
        "penalty": penalty,
    }
