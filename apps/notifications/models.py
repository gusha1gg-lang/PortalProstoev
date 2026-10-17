"""
Модуль «Уведомления»: правила рассылки, получатели и журнал отправок.

Идея простыми словами:
    Правило — «по какому событию», «кому» и «что написать».
    Получатель — конкретный адрес электронной почты.
    Журнал — что уже отправлено, чтобы не слать одно и то же дважды.

Сейчас канал один — email. Другие каналы (например, Telegram) добавляются позже
без переделки правил: канал выбирается полем `channel` и реализуется отдельным классом
(см. `channels.py`).
"""
from django.db import models
from django.db.models import Q

from apps.catalog.models import TimeStampedModel, Workshop
from apps.downtimes.models import DowntimeCase, DowntimeEvent


class NotificationRule(TimeStampedModel):
    """Правило: по какому событию, кому и с каким текстом отправлять письмо."""

    class Event(models.TextChoices):
        NEW_INCIDENT = "new_incident", "Новый инцидент (простой по вине ИТ)"
        SLA_WARNING = "sla_warning", "Предупреждение SLA (приближение к лимиту)"
        SLA_BREACH = "sla_breach", "Эскалация SLA (лимит превышен)"
        DIGEST = "digest", "Периодическая сводка"
        MENTION = "mention", "Упоминание в чате разбора простоя"

    class Channel(models.TextChoices):
        EMAIL = "email", "Email"

    name = models.CharField("Название правила", max_length=255)
    event = models.CharField("Событие", max_length=32, choices=Event.choices)
    channel = models.CharField("Канал", max_length=16, choices=Channel.choices, default=Channel.EMAIL)

    # Пусто = правило действует для всех цехов.
    workshop = models.ForeignKey(
        Workshop,
        on_delete=models.CASCADE,
        related_name="notification_rules",
        verbose_name="Цех",
        null=True,
        blank=True,
    )

    # Для предупреждения SLA: при каком проценте лимита отправлять (по умолчанию 80).
    threshold_percent = models.PositiveSmallIntegerField("Порог, % от лимита", default=80)

    is_active = models.BooleanField("Активно", default=True)
    subject_template = models.CharField("Тема письма (шаблон)", max_length=255, blank=True)
    body_template = models.TextField("Текст письма (шаблон)", blank=True)

    class Meta:
        verbose_name = "Правило уведомления"
        verbose_name_plural = "Правила уведомлений"
        ordering = ["event", "name"]

    def __str__(self):
        scope = self.workshop.name if self.workshop else "все цеха"
        return f"{self.get_event_display()} · {scope}"


class NotificationRecipient(TimeStampedModel):
    """Получатель письма по правилу (конкретный адрес)."""

    rule = models.ForeignKey(
        NotificationRule, on_delete=models.CASCADE, related_name="recipients", verbose_name="Правило"
    )
    email = models.EmailField("Адрес")
    name = models.CharField("Имя (кому)", max_length=255, blank=True)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Получатель"
        verbose_name_plural = "Получатели"
        ordering = ["rule", "email"]
        constraints = [
            models.UniqueConstraint(fields=["rule", "email"], name="uniq_recipient_per_rule"),
        ]

    def __str__(self):
        return self.name or self.email


class NotificationLog(TimeStampedModel):
    """Журнал отправки: что, кому, когда и с каким итогом."""

    class Status(models.TextChoices):
        SENT = "sent", "Отправлено"
        FAILED = "failed", "Ошибка"
        SKIPPED = "skipped", "Пропущено"

    rule = models.ForeignKey(
        NotificationRule,
        on_delete=models.SET_NULL,
        related_name="logs",
        verbose_name="Правило",
        null=True,
        blank=True,
    )
    event = models.CharField("Событие", max_length=32, choices=NotificationRule.Event.choices)
    channel = models.CharField("Канал", max_length=16, choices=NotificationRule.Channel.choices)
    # Ключ «не слать дважды». Заполняется только у успешных отправок, поэтому ошибку можно повторить.
    dedup_key = models.CharField("Ключ уникальности", max_length=255, blank=True, default="")
    recipients = models.TextField("Получатели", blank=True)
    subject = models.CharField("Тема", max_length=255, blank=True)
    status = models.CharField("Итог", max_length=16, choices=Status.choices)
    error = models.TextField("Ошибка", blank=True)
    sent_at = models.DateTimeField("Отправлено", null=True, blank=True)

    related_event = models.ForeignKey(
        DowntimeEvent,
        on_delete=models.SET_NULL,
        related_name="notifications",
        verbose_name="Простой",
        null=True,
        blank=True,
    )
    related_case = models.ForeignKey(
        DowntimeCase,
        on_delete=models.SET_NULL,
        related_name="notifications",
        verbose_name="Кейс",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Отправленное уведомление"
        verbose_name_plural = "Журнал уведомлений"
        ordering = ["-created_at"]
        constraints = [
            # Ключ уникален, но пустой — не считается (ошибки можно повторять).
            models.UniqueConstraint(
                fields=["dedup_key"],
                condition=~Q(dedup_key=""),
                name="uniq_notification_dedup_key",
            ),
        ]

    def __str__(self):
        return f"{self.subject or self.event} → {self.recipients} ({self.get_status_display()})"
