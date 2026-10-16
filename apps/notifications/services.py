"""
Логика уведомлений: кому и когда шлём письма, защита от повторов.

Правила лежат в базе (модель NotificationRule + получатели). Здесь — их применение:
    - новый инцидент (простой по вине ИТ);
    - предупреждение SLA (простой приблизился к лимиту по договору);
    - эскалация SLA (лимит превышен);
    - периодическая сводка.

Одно и то же письмо не уходит дважды: у успешной отправки есть ключ уникальности
(`dedup_key`) в журнале. Ошибку отправки можно повторить при следующем запуске.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.template import Context, Template
from django.utils import timezone

from apps.catalog.models import Workshop
from apps.sla.services import sla_summary

from .channels import Message, get_channel
from .models import NotificationLog, NotificationRule

ZERO = Decimal("0")


# --- Шаблоны писем по умолчанию (если в правиле не задан свой текст) ---

def _default_payload(event: str, ctx: dict) -> tuple[str, str]:
    """Собирает тему и текст письма по умолчанию для события."""
    if event == NotificationRule.Event.NEW_INCIDENT:
        subject = f"Новый простой по вине ИТ: {ctx.get('title', '')}"
        body = (
            f"Зафиксирован новый простой по вине ИТ-службы.\n\n"
            f"Цех: {ctx.get('workshop', '—')}\n"
            f"Начало: {ctx.get('when', '—')}\n"
            f"Длительность: {ctx.get('duration_min', 0)} мин\n"
            f"Описание: {ctx.get('note') or '—'}\n\n"
            f"Проверьте и подтвердите простой в портале."
        )
        return subject, body

    if event == NotificationRule.Event.SLA_WARNING:
        subject = f"Предупреждение SLA: {ctx.get('workshop', '—')}"
        body = (
            f"Простои по вине ИТ приближаются к лимиту по договору SLA.\n\n"
            f"Цех: {ctx.get('workshop', '—')}\n"
            f"Период: {ctx.get('period', '—')}\n"
            f"Простои: {ctx.get('downtime_min', 0)} мин из допустимых {ctx.get('allowed_min', 0)} мин "
            f"({ctx.get('percent_used', 0)}%)\n"
            f"Целевая доступность: {ctx.get('target_availability', '—')}%\n\n"
            f"Примите меры, чтобы не превысить лимит."
        )
        return subject, body

    if event == NotificationRule.Event.SLA_BREACH:
        subject = f"Превышение лимита SLA: {ctx.get('workshop', '—')}"
        body = (
            f"Лимит простоя по договору SLA превышен.\n\n"
            f"Цех: {ctx.get('workshop', '—')}\n"
            f"Период: {ctx.get('period', '—')}\n"
            f"Простои: {ctx.get('downtime_min', 0)} мин, допустимо {ctx.get('allowed_min', 0)} мин "
            f"({ctx.get('percent_used', 0)}%)\n"
            f"Целевая доступность: {ctx.get('target_availability', '—')}%\n"
            f"Ориентировочный штраф: {ctx.get('penalty', 0)} ₽\n\n"
            f"Требуется эскалация."
        )
        return subject, body

    if event == NotificationRule.Event.DIGEST:
        subject = f"Сводка простоев за {ctx.get('period', '—')}"
        body = (
            f"Сводка по простоям по вине ИТ за {ctx.get('period', '—')}.\n\n"
            f"Инцидентов: {ctx.get('incident_count', 0)}\n"
            f"Простои: {ctx.get('downtime_hours', 0)} ч\n"
            f"Потери: {ctx.get('loss', 0)} ₽\n"
            f"Доступность: {ctx.get('availability', 100)}%\n"
            f"Штраф SLA: {ctx.get('penalty', 0)} ₽\n"
        )
        return subject, body

    return event, ctx.get("title", "")


def _render(rule: NotificationRule, ctx: dict) -> tuple[str, str]:
    """Тема и текст: берём шаблон из правила, иначе — по умолчанию."""
    default_subject, default_body = _default_payload(rule.event, ctx)
    subject = _from_template(rule.subject_template, ctx) or default_subject
    body = _from_template(rule.body_template, ctx) or default_body
    return subject, body


def _from_template(text: str, ctx: dict) -> str:
    """Подставляет значения в пользовательский шаблон (если он задан)."""
    if not text:
        return ""
    return Template(text).render(Context(ctx))


def _recipients(rule: NotificationRule) -> list[str]:
    """Активные адреса получателей правила."""
    return [r.email for r in rule.recipients.filter(is_active=True) if r.email]


def rules_for(event: str, workshop=None) -> list[NotificationRule]:
    """
    Активные правила для события. Правило без цеха — для всех;
    с цехом — только для него.
    """
    rules = NotificationRule.objects.filter(event=event, is_active=True).select_related("workshop")
    return [
        rule
        for rule in rules
        if rule.workshop_id is None or (workshop is not None and rule.workshop_id == workshop.pk)
    ]


@dataclass
class SendResult:
    """Краткий итог отправки (для команд и отчётов)."""

    subject: str
    recipients: list[str]
    status: str


def send_rule(rule: NotificationRule, dedup_key: str, ctx: dict, *, case=None, event=None):
    """
    Отправляет письмо по правилу. Возвращает запись журнала или None, если
    письмо уже отправляли или у правила нет получателей.
    """
    if dedup_key and NotificationLog.objects.filter(dedup_key=dedup_key).exists():
        return None  # уже отправляли — не дублируем

    recipients = _recipients(rule)
    if not recipients:
        return None  # некому слать

    subject, body = _render(rule, ctx)
    status, error = get_channel(rule.channel).send(
        Message(subject=subject, body=body, recipients=recipients)
    )

    return NotificationLog.objects.create(
        rule=rule,
        event=rule.event,
        channel=rule.channel,
        # Ключ сохраняем только у успешных отправок — тогда ошибку можно повторить.
        dedup_key=dedup_key if status == NotificationLog.Status.SENT else "",
        recipients=", ".join(recipients),
        subject=subject,
        status=status,
        error=error,
        sent_at=timezone.now() if status == NotificationLog.Status.SENT else None,
        related_case=case,
        related_event=event,
    )


def _local(value=None):
    """Локальное время (или None)."""
    if value is None:
        return None
    return timezone.localtime(value) if timezone.is_aware(value) else value


# --- События ---

def notify_new_incident(downtime_event) -> list[NotificationLog]:
    """Уведомляет о новом простое по вине ИТ."""
    workshop = downtime_event.workshop
    started = _local(downtime_event.started_at)
    ctx = {
        "title": downtime_event.note or f"Простой · {workshop.name}",
        "workshop": workshop.name,
        "when": started.strftime("%d.%m.%Y %H:%M") if started else "—",
        "duration_min": downtime_event.duration_min,
        "note": downtime_event.note,
    }
    logs = []
    for rule in rules_for(NotificationRule.Event.NEW_INCIDENT, workshop):
        key = f"new_incident:{rule.pk}:event:{downtime_event.pk}"
        log = send_rule(rule, key, ctx, event=downtime_event)
        if log:
            logs.append(log)
    return logs


def _send_sla(event: str, workshop, summary: dict, period: str, downtime: Decimal, allowed: Decimal):
    """Отправляет предупреждение или эскалацию SLA по всем подходящим правилам."""
    percent = (downtime / allowed * Decimal(100)).quantize(Decimal("1")) if allowed else ZERO
    contract = summary.get("contract")
    ctx = {
        "workshop": workshop.name,
        "period": period,
        "downtime_min": int(downtime),
        "allowed_min": int(allowed),
        "percent_used": int(percent),
        "target_availability": contract.target_availability if contract else "—",
        "penalty": summary["penalty"],
    }
    logs = []
    for rule in rules_for(event, workshop):
        key = f"{event}:{rule.pk}:workshop:{workshop.pk}:{period}"
        log = send_rule(rule, key, ctx)
        if log:
            logs.append(log)
    return logs


def check_escalations(now=None) -> list[NotificationLog]:
    """
    Проверяет лимиты SLA по всем цехам за текущий месяц и рассылает
    предупреждения/эскалации. Запускать по расписанию (cron, каждые 5–10 минут).
    """
    moment = _local(now) or timezone.localtime()
    period = f"{moment.year:04d}-{moment.month:02d}"

    logs = []
    for workshop in Workshop.objects.filter(is_active=True).order_by("name"):
        summary = sla_summary(workshop, moment.year, moment.month)
        allowed = summary["allowed_min"]
        if allowed is None or allowed <= 0:
            continue  # нет договора или нулевой лимит — проверять нечего

        downtime = Decimal(summary["downtime_min"])
        if downtime > allowed:
            logs += _send_sla(
                NotificationRule.Event.SLA_BREACH, workshop, summary, period, downtime, Decimal(allowed)
            )
            continue

        for rule in rules_for(NotificationRule.Event.SLA_WARNING, workshop):
            threshold = Decimal(rule.threshold_percent or 80)
            if downtime >= Decimal(allowed) * threshold / Decimal(100):
                logs += _send_sla(
                    NotificationRule.Event.SLA_WARNING, workshop, summary, period, downtime, Decimal(allowed)
                )
                break  # одно предупреждение на цех (ключ всё равно не даст дубль)
    return logs


def send_digest(now=None) -> list[NotificationLog]:
    """Отправляет периодическую сводку (ежедневно). Запускать по расписанию (cron)."""
    from apps.reports.services import kpi  # локальный импорт, чтобы не плодить зависимости на старте

    moment = _local(now) or timezone.localtime()
    period = f"{moment.year:04d}-{moment.month:02d}"
    data = kpi(moment.year, moment.month)

    ctx = {
        "period": period,
        "date": moment.strftime("%d.%m.%Y"),
        "incident_count": data["incident_count"],
        "downtime_hours": data["downtime_hours"],
        "loss": data["loss"],
        "availability": data["availability"],
        "penalty": data["penalty"],
    }
    logs = []
    for rule in rules_for(NotificationRule.Event.DIGEST, None):
        key = f"digest:{rule.pk}:{period}:{moment.date().isoformat()}"
        log = send_rule(rule, key, ctx)
        if log:
            logs.append(log)
    return logs


def send_test(to_email: str) -> str:
    """Отправляет проверочное письмо на адрес (для команды notify_test)."""
    status, error = get_channel(NotificationRule.Channel.EMAIL).send(
        Message(
            subject="PortalProstoev: проверка почты",
            body="Это проверочное письмо от портала учёта простоев. Если вы его видите — почта настроена.",
            recipients=[to_email],
        )
    )
    return f"{status}: {error}" if error else status
