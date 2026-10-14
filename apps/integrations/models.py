"""
Модели модуля «Интеграции»: связь простой/кейс ↔ тикет OMNITRACKER.

Простой или кейс может быть связан с одним или несколькими тикетами (и наоборот),
поэтому связь хранится отдельной таблицей.
"""
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
