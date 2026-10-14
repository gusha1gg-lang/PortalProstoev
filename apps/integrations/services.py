"""
Логика интеграций: импорт простоев из источника и синхронизация тикетов.

Здесь собраны правила, которые должны работать одинаково и в mock-, и в live-режиме:
    - фильтр «наши простои» (СЛУЖБА = ДИТ);
    - сопоставление строк источника со справочниками (цех → участок → агрегат);
    - идемпотентность (повторный импорт не создаёт дублей);
    - отчёт о том, что создано, пропущено и почему.
"""
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, time

from django.utils import timezone

from apps.catalog.models import Section, Unit, Workshop
from apps.downtimes.models import DowntimeEvent
from apps.downtimes.services import save_with_audit

from .factory import get_oracle_source, get_omnitracker
from .models import TicketLink
from .oracle import DIT_SERVICE
from .omnitracker import Ticket

# Колонки, из которых складывается отпечаток строки (для идемпотентности).
FINGERPRINT_FIELDS = ("НАЧАЛО", "КОНЕЦ", "ЦЕХ", "УЧАСТОК", "АГГРЕГАТ", "ФИО", "ПРИМЕЧАНИЕ")


@dataclass
class ImportReport:
    """Что получилось после импорта (для понятного отчёта человеку)."""

    total: int = 0
    created: int = 0
    skipped_existing: int = 0
    updated: int = 0
    filtered_out: int = 0  # не наша служба
    skipped_missing: int = 0  # не нашли цех/участок/агрегат в справочнике
    problems: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        lines = [
            f"Всего строк из источника: {self.total}",
            f"  создано: {self.created}",
            f"  уже было (пропущено): {self.skipped_existing}",
            f"  обновлено: {self.updated}",
            f"  не наша служба (отфильтровано): {self.filtered_out}",
            f"  не найдено в справочнике (пропущено): {self.skipped_missing}",
        ]
        if self.problems:
            lines.append("Замечания:")
            lines.extend(f"  - {problem}" for problem in self.problems)
        return "\n".join(lines)


def parse_dt(text):
    """Разбирает дату-время источника «2026-10-10 15:01:25» (или без секунд)."""
    if not text:
        return None
    if isinstance(text, datetime):
        value = text
    else:
        value = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                value = datetime.strptime(str(text).strip(), fmt)
                break
            except ValueError:
                continue
        if value is None:
            return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    return value


def row_is_ours(row) -> bool:
    """True, если строка относится к нашей службе (ДИТ)."""
    return str(row.get("СЛУЖБА", "")).strip().upper() == DIT_SERVICE.upper()


def row_fingerprint(row) -> str:
    """Устойчивый отпечаток строки — используется как внешний ID для идемпотентности."""
    raw = "|".join(str(row.get(field_name, "")).strip() for field_name in FINGERPRINT_FIELDS)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


def _resolve_catalog(row, create_missing):
    """
    Сопоставляет ЦЕХ / УЧАСТОК / АГГРЕГАТ справочникам.

    Возвращает (workshop, section, unit, problems). Если что-то не нашлось (и нельзя создать) —
    вернёт problems, а вызывающий код пропустит строку.
    """
    problems = []
    workshop_name = str(row.get("ЦЕХ", "")).strip()
    section_name = str(row.get("УЧАСТОК", "")).strip()
    unit_name = str(row.get("АГГРЕГАТ", "")).strip()

    workshops = list(Workshop.objects.filter(name=workshop_name))
    if len(workshops) != 1:
        # Предприятие в источнике не указано, поэтому неоднозначный цех не угадываем.
        problems.append(
            f"цех «{workshop_name}»: найдено {len(workshops)} совпадений (нужно ровно одно)"
        )
        return None, None, None, problems
    workshop = workshops[0]

    section = None
    if section_name:
        sections = list(Section.objects.filter(workshop=workshop, name=section_name))
        if len(sections) == 0 and create_missing:
            section = Section.objects.create(workshop=workshop, name=section_name)
        elif len(sections) == 1:
            section = sections[0]
        else:
            problems.append(
                f"участок «{section_name}» в цехе «{workshop_name}»: найдено {len(sections)} совпадений"
            )
            return None, None, None, problems

    unit = None
    if section is not None and unit_name:
        units = list(Unit.objects.filter(section=section, name=unit_name))
        if len(units) == 0 and create_missing:
            unit = Unit.objects.create(section=section, name=unit_name)
        elif len(units) == 1:
            unit = units[0]
        else:
            problems.append(f"агрегат «{unit_name}» на участке «{section_name}»: найдено {len(units)} совпадений")
            return None, None, None, problems

    return workshop, section, unit, problems


def _build_data(row, create_missing):
    """Преобразует строку источника в поля нашего простоя. При проблемах вернёт (None, problems)."""
    started_at = parse_dt(row.get("НАЧАЛО"))
    ended_at = parse_dt(row.get("КОНЕЦ"))
    if started_at is None:
        return None, [f"не разобрана дата начала: «{row.get('НАЧАЛО')}»"]

    workshop, section, unit, problems = _resolve_catalog(row, create_missing)
    if problems:
        return None, problems

    data = {
        "started_at": started_at,
        "ended_at": ended_at,
        "workshop": workshop,
        "section": section,
        "unit": unit,
        "note": str(row.get("ПРИМЕЧАНИЕ", "")).strip(),
        "recorded_by_name": str(row.get("ФИО", "")).strip(),
        "service": str(row.get("СЛУЖБА", "")).strip() or DIT_SERVICE,
        "fault_side": DowntimeEvent.FaultSide.IT,
    }
    return data, []


def import_downtimes(since=None, until=None, create_missing=False, update=False, source=None):
    """
    Импортирует простои из источника (mock или live) в базу портала.

    Идемпотентно: повторный импорт не создаёт дублей (сверка по внешнему ID — отпечатку строки).
    Возвращает ImportReport с итогами.
    """
    source = source or get_oracle_source()
    rows = source.fetch_rows(since=since, until=until)
    report = ImportReport(total=len(rows))

    for row in rows:
        if not row_is_ours(row):
            report.filtered_out += 1
            continue

        data, problems = _build_data(row, create_missing)
        if data is None:
            report.skipped_missing += 1
            report.problems.extend(problems)
            continue

        external_id = row_fingerprint(row)
        existing = DowntimeEvent.objects.filter(
            source=DowntimeEvent.Source.ORACLE, external_id=external_id
        ).first()

        if existing is not None:
            if update:
                if _apply_update(existing, data):
                    report.updated += 1
                else:
                    report.skipped_existing += 1
            else:
                report.skipped_existing += 1
            continue

        event = DowntimeEvent(
            source=DowntimeEvent.Source.ORACLE,
            external_id=external_id,
            status=DowntimeEvent.Status.NEW,
            raw=dict(row.data),
            **data,
        )
        save_with_audit(event, user=None, comment="Импорт из Oracle")
        report.created += 1

    return report


def _apply_update(event, data) -> bool:
    """Обновляет изменившиеся поля уже загруженного простоя. True — если что-то поменялось."""
    changed = False
    if event.ended_at != data["ended_at"]:
        event.ended_at = data["ended_at"]
        changed = True
    if (event.note or "") != (data["note"] or ""):
        event.note = data["note"]
        changed = True
    if (event.recorded_by_name or "") != (data["recorded_by_name"] or ""):
        event.recorded_by_name = data["recorded_by_name"]
        changed = True
    if changed:
        save_with_audit(event, user=None, comment="Обновление из Oracle")
    return changed


# --- Тикеты OMNITRACKER ---

def fetch_tickets(external_ids=None) -> list[Ticket]:
    """Забирает тикеты из OMNITRACKER (mock или live)."""
    return get_omnitracker().fetch_tickets(external_ids=external_ids)


def link_ticket(ticket: Ticket, event=None, case=None) -> TicketLink:
    """Создаёт (или обновляет) связь тикета с простым или кейсом."""
    if event is None and case is None:
        raise ValueError("Нужно указать простой или кейс для связи с тикетом.")

    link, _ = TicketLink.objects.get_or_create(
        source=TicketLink.Source.OMNITRACKER,
        external_id=ticket.external_id,
        event=event,
        case=case,
    )
    link.title = ticket.title
    link.status = ticket.status
    link.url = ticket.url
    link.synced_at = timezone.now()
    link.save()
    return link


def sync_tickets(source=None) -> dict:
    """
    Обновляет уже привязанные тикеты из OMNITRACKER.

    Новые связи автоматически не создаём: правило «какой тикет к какому инциденту» ещё
    согласуется (см. question.md, В16). Возвращает сводку.
    """
    tracker = source or get_omnitracker()
    links = list(TicketLink.objects.filter(source=TicketLink.Source.OMNITRACKER))
    if not links:
        return {"tickets": 0, "linked": 0, "unlinked": 0, "updated": 0}

    ids = sorted({link.external_id for link in links})
    tickets = {t.external_id: t for t in tracker.fetch_tickets(external_ids=ids)}

    updated = 0
    for link in links:
        ticket = tickets.get(link.external_id)
        if ticket is None:
            continue
        link.title = ticket.title
        link.status = ticket.status
        link.url = ticket.url
        link.synced_at = timezone.now()
        link.save()
        updated += 1

    fetched = tracker.fetch_tickets()
    return {
        "tickets": len(fetched),
        "linked": len(links),
        "unlinked": max(len(fetched) - len({link.external_id for link in links}), 0),
        "updated": updated,
    }


def month_bounds(year: int, month: int):
    """Границы месяца как datetime с часовым поясом (для импорта за период)."""
    start = timezone.make_aware(datetime(year, month, 1))
    if month == 12:
        end = timezone.make_aware(datetime(year + 1, 1, 1))
    else:
        end = timezone.make_aware(datetime(year, month + 1, 1))
    return start, end


def day_start(value):
    """Начало дня по дате (для параметра --since)."""
    return timezone.make_aware(datetime.combine(value, time.min))
