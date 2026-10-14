"""
Модуль «Простои»: сами события простоя и журнал изменений (аудит).

Схема (по-простому):
    Простой (DowntimeEvent) — что случилось, когда и где.
    Журнал (DowntimeEventLog) — кто и когда менял запись.

Объединение простоев в «кейсы» — это следующий этап (4). Расчёт потерь и SLA — этап 5.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.catalog.models import (
    ItFaultCategory,
    ItFaultSubcategory,
    Section,
    Unit,
    Workshop,
)


class TimeStampedModel(models.Model):
    """Общая база: дата создания и последнего изменения записи."""

    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    class Meta:
        abstract = True


class DowntimeEvent(TimeStampedModel):
    """Одно событие простоя: когда, где, по какой причине и в каком статусе."""

    class Status(models.TextChoices):
        NEW = "new", "Новый"
        CONFIRMED = "confirmed", "Подтверждён"
        CLOSED = "closed", "Закрыт"
        CANCELED = "canceled", "Отменён"

    class FaultSide(models.TextChoices):
        IT = "it", "Вина ИТ"
        FOREIGN = "foreign", "Другая служба"
        UNKNOWN = "unknown", "Не определена"

    class Source(models.TextChoices):
        MANUAL = "manual", "Вручную"
        ORACLE = "oracle", "Oracle"
        FILE = "file", "Файл"

    # --- Когда ---
    started_at = models.DateTimeField("Начало")
    ended_at = models.DateTimeField("Окончание", null=True, blank=True)
    # Длительность храним, но всегда пересчитываем из начала/конца при сохранении.
    duration_min = models.PositiveIntegerField("Длительность, мин", default=0, editable=False)

    # --- Где ---
    workshop = models.ForeignKey(
        Workshop, on_delete=models.PROTECT, related_name="downtimes", verbose_name="Цех"
    )
    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="downtimes",
        verbose_name="Участок",
        null=True,
        blank=True,
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="downtimes",
        verbose_name="Агрегат",
        null=True,
        blank=True,
    )

    # --- Классификация вины ---
    service = models.CharField("Служба", max_length=64, default="ДИТ")
    fault_side = models.CharField(
        "Вина", max_length=16, choices=FaultSide.choices, default=FaultSide.IT
    )
    fault_category = models.ForeignKey(
        ItFaultCategory,
        on_delete=models.PROTECT,
        related_name="downtimes",
        verbose_name="Категория вины",
        null=True,
        blank=True,
    )
    fault_subcategory = models.ForeignKey(
        ItFaultSubcategory,
        on_delete=models.PROTECT,
        related_name="downtimes",
        verbose_name="Подкатегория вины",
        null=True,
        blank=True,
    )

    # --- Описание ---
    note = models.TextField("Примечание", blank=True)
    recorded_by_name = models.CharField("Кто зафиксировал (ФИО)", max_length=255, blank=True)

    # --- Потери (этап 5) ---
    # Непроизведённые тонны. Для одиночного простоя — здесь; для кейса — у одного из событий либо на карточке кейса.
    unproduced_tons = models.DecimalField(
        "Непроизведённые тонны", max_digits=12, decimal_places=3, default=0
    )

    # --- Состояние и источник ---
    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.NEW)
    source = models.CharField("Источник", max_length=16, choices=Source.choices, default=Source.MANUAL)
    external_id = models.CharField("Внешний ID", max_length=128, null=True, blank=True)
    raw = models.JSONField("Исходные данные", null=True, blank=True)

    # --- Объединение в кейс (этап 4) ---
    # Пусто = простой считается сам по себе. Если задан — учитывается в кейсе, отдельно не считается.
    case = models.ForeignKey(
        "DowntimeCase",
        on_delete=models.SET_NULL,
        related_name="events",
        verbose_name="Кейс",
        null=True,
        blank=True,
    )

    # --- Аудит авторства ---
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="downtimes_created",
        verbose_name="Создал",
        null=True,
        blank=True,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="downtimes_updated",
        verbose_name="Изменил",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Простой"
        verbose_name_plural = "Простои"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["started_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["workshop"]),
        ]
        constraints = [
            # Конец не может быть раньше начала.
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True) | Q(ended_at__gte=models.F("started_at")),
                name="downtime_ended_after_started",
            ),
            # Внешний ID уникален в пределах источника (для повторного импорта).
            models.UniqueConstraint(
                fields=["source", "external_id"],
                condition=Q(external_id__isnull=False),
                name="uniq_source_external_id",
            ),
        ]

    def clean(self):
        """Дополнительная проверка при сохранении из форм/админки."""
        if self.ended_at and self.started_at and self.ended_at < self.started_at:
            raise ValidationError({"ended_at": "Окончание не может быть раньше начала."})

    def save(self, *args, **kwargs):
        """Пересчитываем длительность и нормализуем внешний ID перед записью."""
        if self.ended_at and self.started_at:
            delta = self.ended_at - self.started_at
            self.duration_min = max(int(delta.total_seconds() // 60), 0)
        else:
            self.duration_min = 0
        # Пустая строка ломает уникальность внешнего ID — храним None.
        if not self.external_id:
            self.external_id = None
        super().save(*args, **kwargs)

    def __str__(self):
        started = timezone.localtime(self.started_at) if timezone.is_aware(self.started_at) else self.started_at
        return f"{started:%d.%m.%Y %H:%M} · {self.workshop.name} · {self.duration_min} мин"


class DowntimeEventLog(TimeStampedModel):
    """Запись в журнале: кто и что изменил в простоях."""

    class Action(models.TextChoices):
        CREATED = "created", "Создание"
        UPDATED = "updated", "Изменение"
        STATUS = "status", "Смена статуса"
        MERGED = "merged", "Объединение"  # пригодится на этапе 4

    event = models.ForeignKey(
        DowntimeEvent, on_delete=models.CASCADE, related_name="logs", verbose_name="Простой"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="downtime_logs",
        verbose_name="Кто",
        null=True,
        blank=True,
    )
    action = models.CharField("Действие", max_length=16, choices=Action.choices)
    changes = models.JSONField("Что изменилось", default=dict, blank=True)
    comment = models.CharField("Комментарий", max_length=255, blank=True)

    class Meta:
        verbose_name = "Запись журнала"
        verbose_name_plural = "Журнал простоев"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_action_display()} · {self.event_id} · {self.created_at:%d.%m.%Y %H:%M}"


class DowntimeCase(TimeStampedModel):
    """
    Кейс — «настоящий» инцидент, в который собраны дублирующие записи о простоях.

    Длительность считается объединением интервалов входящих событий:
    перекрывающиеся куски считаются один раз (без двойного счёта).
    """

    class Status(models.TextChoices):
        OPEN = "open", "Открыт"
        CONFIRMED = "confirmed", "Подтверждён"
        CLOSED = "closed", "Закрыт"
        CANCELED = "canceled", "Отменён"

    number = models.CharField("Номер", max_length=32, unique=True, editable=False)
    title = models.CharField("Название", max_length=255)
    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.OPEN)
    fault_side = models.CharField(
        "Вина", max_length=16, choices=DowntimeEvent.FaultSide.choices, default=DowntimeEvent.FaultSide.IT
    )
    fault_category = models.ForeignKey(
        ItFaultCategory,
        on_delete=models.PROTECT,
        related_name="cases",
        verbose_name="Категория вины",
        null=True,
        blank=True,
    )
    fault_subcategory = models.ForeignKey(
        ItFaultSubcategory,
        on_delete=models.PROTECT,
        related_name="cases",
        verbose_name="Подкатегория вины",
        null=True,
        blank=True,
    )

    # Границы и длительность — считаются из входящих событий (см. services.recalc_case).
    started_at = models.DateTimeField("Начало", null=True, blank=True, editable=False)
    ended_at = models.DateTimeField("Окончание", null=True, blank=True, editable=False)
    duration_min = models.PositiveIntegerField("Длительность, мин", default=0, editable=False)

    # Дополнительные тонны по кейсу целиком (когда тонны нельзя разнести по участкам).
    unproduced_tons = models.DecimalField(
        "Непроизведённые тонны", max_digits=12, decimal_places=3, default=0
    )

    note = models.TextField("Описание", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="cases_created",
        verbose_name="Создал",
        null=True,
        blank=True,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="cases_updated",
        verbose_name="Изменил",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Кейс"
        verbose_name_plural = "Кейсы"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["started_at"]),
            models.Index(fields=["status"]),
        ]

    def save(self, *args, **kwargs):
        """Автоматически присваиваем номер кейса вида «К-2026-0001»."""
        if not self.number:
            year = timezone.now().year
            prefix = f"К-{year}-"
            last = DowntimeCase.objects.filter(number__startswith=prefix).order_by("-number").first()
            seq = int(last.number.rsplit("-", 1)[-1]) + 1 if last else 1
            self.number = f"{prefix}{seq:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} · {self.title}"


class DowntimeCaseLog(TimeStampedModel):
    """Запись в журнале кейса: кто и что изменил."""

    class Action(models.TextChoices):
        CREATED = "created", "Создание"
        UPDATED = "updated", "Изменение"
        STATUS = "status", "Смена статуса"
        MERGED = "merged", "Объединение"
        UNMERGED = "unmerged", "Разъединение"

    case = models.ForeignKey(
        DowntimeCase, on_delete=models.CASCADE, related_name="logs", verbose_name="Кейс"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="downtime_case_logs",
        verbose_name="Кто",
        null=True,
        blank=True,
    )
    action = models.CharField("Действие", max_length=16, choices=Action.choices)
    changes = models.JSONField("Что изменилось", default=dict, blank=True)
    comment = models.CharField("Комментарий", max_length=255, blank=True)

    class Meta:
        verbose_name = "Запись журнала кейса"
        verbose_name_plural = "Журнал кейсов"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_action_display()} · {self.case_id} · {self.created_at:%d.%m.%Y %H:%M}"
