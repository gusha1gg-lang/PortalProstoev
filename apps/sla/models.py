"""
Модуль «Потери и SLA».

Хранит договоры SLA (целевая доступность и штраф) по цехам.
Сами расчёты потерь, доступности, MTTR/MTBF — в `services.py` (одно место на весь портал).
"""
from decimal import Decimal

from django.db import models
from django.db.models import F, Q

from apps.catalog.models import TimeStampedModel, Workshop


class SlaContract(TimeStampedModel):
    """
    Договор SLA по цеху. Версионируется по датам: для расчёта берётся
    договор, действовавший на начало периода. Если цех не задан — договор
    действует для всех цехов (общий).
    """

    workshop = models.ForeignKey(
        Workshop,
        on_delete=models.PROTECT,
        related_name="sla_contracts",
        verbose_name="Цех",
        null=True,
        blank=True,
    )
    name = models.CharField("Название", max_length=255)
    target_availability = models.DecimalField(
        "Целевая доступность, %", max_digits=5, decimal_places=2, default=Decimal("99.50")
    )
    penalty_per_hour = models.DecimalField(
        "Штраф за час сверх лимита, ₽", max_digits=14, decimal_places=2, default=Decimal("0")
    )
    valid_from = models.DateField("Действует с")
    valid_to = models.DateField("Действует по", null=True, blank=True)
    is_active = models.BooleanField("Активен", default=True)
    note = models.CharField("Примечание", max_length=255, blank=True)

    class Meta:
        verbose_name = "Договор SLA"
        verbose_name_plural = "Договоры SLA"
        ordering = ["workshop__name", "-valid_from"]
        constraints = [
            # Дата окончания не может быть раньше даты начала.
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gte=F("valid_from")),
                name="sla_valid_to_after_from",
            ),
            # Доступность задаётся в процентах, от 0 до 100.
            models.CheckConstraint(
                condition=Q(target_availability__gte=0) & Q(target_availability__lte=100),
                name="sla_target_between_0_and_100",
            ),
        ]

    def __str__(self):
        scope = self.workshop.name if self.workshop else "Все цеха"
        return f"{scope}: SLA {self.target_availability}%"
