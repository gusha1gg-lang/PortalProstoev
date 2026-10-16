"""
Модели модуля «Интеграции»: связь простой/кейс ↔ тикет OMNITRACKER и журнал
запусков синхронизации (SyncRun).

Простой или кейс может быть связан с одним или несколькими тикетами (и наоборот),
поэтому связь хранится отдельной таблицей. SyncRun хранит итог каждого запуска
синхронизации с источником (этап 11.6).
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.catalog.models import TimeStampedModel
from apps.downtimes.models import DowntimeCase, DowntimeEvent


class TicketLink(TimeStampedModel):
    """Связь нашего инцидента (простоя или кейса) с внешним тикетом."""

    class Source(models.TextChoices):
        OMNITRACKER = "omniltracker", "OMNITRACKER"

    source = models.CharField("Система", max_length=32, choices=Source.choices, default=Source.OMNITRACKER)
    external_id = models.CharField("Номер тикета", max_length=128)
    title = models.CharField("Тема тикета", max_length=255, blank=True)
    status = models.CharField("Статус тикета", max_length=64, blank=True)
    url = models.URLField("Ссылка на тикет", blank=True)

    # Связь либо с простым, либо с кейсом (что-то одно обязательно).
    event = models.ForeignKey(
        DowntimeEvent,
        on_delete=models.CASCADE,
        related_name="ticket_links",
        verbose_name="Простой",
        null=True,
        blank=True,
    )
    case = models.ForeignKey(
        DowntimeCase,
        on_delete=models.CASCADE,
        related_name="ticket_links",
        verbose_name="Кейс",
        null=True,
        blank=True,
    )
    synced_at = models.DateTimeField("Синхронизировано", null=True, blank=True)

    class Meta:
        verbose_name = "Связь с тикетом"
        verbose_name_plural = "Связи с тикетами"
        ordering = ["-created_at"]
        constraints = [
            # Должна быть указана цель связи: простой или кейс.
            models.CheckConstraint(
                condition=Q(event__isnull=False) | Q(case__isnull=False),
                name="ticket_link_has_target",
            ),
            # Один и тот же тикет не привязывается дважды к одному простому.
            models.UniqueConstraint(
                fields=["source", "external_id", "event"],
                condition=Q(event__isnull=False),
                name="uniq_ticket_link_to_event",
            ),
            # ... и к одному кейсу.
            models.UniqueConstraint(
                fields=["source", "external_id", "case"],
                condition=Q(case__isnull=False),
                name="uniq_ticket_link_to_case",
            ),
        ]

    def __str__(self):
        target = self.case or self.event
        return f"{self.external_id} ↔ {target}"


class SyncRun(TimeStampedModel):
    """Журнал запуска синхронизации: когда, каким способом и что получилось.

    Каждый запуск (автосбор по расписанию или кнопка «Забрать сейчас») оставляет здесь
    запись — видно, что и когда подтянулось, сколько строк создали/исправили/сняли.
    """

    class Mode(models.TextChoices):
        AUTO = "auto", "Автосбор"
        MANUAL = "manual", "Вручную"

    class Status(models.TextChoices):
        OK = "ok", "Завершено"
        ERROR = "error", "Ошибка"

    mode = models.CharField("Режим", max_length=8, choices=Mode.choices, default=Mode.AUTO)
    status = models.CharField("Статус", max_length=8, choices=Status.choices, default=Status.OK)
    started_at = models.DateTimeField("Начало")
    finished_at = models.DateTimeField("Окончание", null=True, blank=True)
    since = models.DateTimeField("Период с", null=True, blank=True)
    until = models.DateTimeField("Период по", null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="sync_runs",
        verbose_name="Кто запустил",
        null=True,
        blank=True,
    )

    total = models.IntegerField("Строк в источнике", default=0)
    created = models.IntegerField("Создано", default=0)
    corrected = models.IntegerField("Исправлено", default=0)
    adjusted = models.IntegerField("Скорректировано", default=0)
    removed = models.IntegerField("Снято", default=0)
    skipped_closed = models.IntegerField("Закрытый период (пропущено)", default=0)
    filtered_out = models.IntegerField("Не наша служба", default=0)
    skipped_missing = models.IntegerField("Не найдено в справочнике", default=0)
    report = models.TextField("Отчёт", blank=True)

    class Meta:
        verbose_name = "Запуск синхронизации"
        verbose_name_plural = "Запуски синхронизации"
        ordering = ["-started_at"]

    @property
    def changed(self):
        """Сколько записей потребовало проверки (исправлено/скорректировано/снято)."""
        return self.corrected + self.adjusted + self.removed

    def __str__(self):
        return f"{self.get_mode_display()} · {self.started_at:%d.%m.%Y %H:%M} · {self.get_status_display()}"
