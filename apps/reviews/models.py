"""
Модуль «Разбор простоя» (этап 11.7).

Разбор — это рабочее место по инциденту: хронология, чат, мероприятия и согласование.
Разбор создаётся из одного или нескольких простоев: несколько простоев сначала
объединяются в **инцидент** (он же «кейс», `DowntimeCase`) — так сохраняется правило
«один инцидент = один случай, без двойного счёта». Разбор ссылается на этот инцидент.

Сейчас (шаг 1) в модели только «шапка» разбора: номер, ведущий, статус и связь с инцидентом.
Хронология, чат, мероприятия и согласование добавятся на следующих шагах.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.catalog.models import TimeStampedModel
from apps.downtimes.models import DowntimeCase


class IncidentReview(TimeStampedModel):
    """Разбор одного инцидента (объединённого простоя)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        IN_PROGRESS = "in_progress", "В работе"
        ON_APPROVAL = "on_approval", "На согласовании"
        APPROVED = "approved", "Согласован"
        REWORK = "rework", "На доработке"

    number = models.CharField("Номер", max_length=32, unique=True, editable=False)
    case = models.OneToOneField(
        DowntimeCase,
        on_delete=models.PROTECT,
        related_name="review",
        verbose_name="Инцидент",
    )
    title = models.CharField("Краткое описание", max_length=255, blank=True)
    status = models.CharField(
        "Статус", max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    lead = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="led_reviews",
        verbose_name="Ведущий",
    )
    summary = models.TextField("Итоги разбора", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_reviews",
        verbose_name="Создал",
    )

    class Meta:
        verbose_name = "Разбор простоя"
        verbose_name_plural = "Разборы простоев"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        """Автоматически присваиваем номер вида «РП-2026-0001»."""
        if not self.number:
            year = timezone.now().year
            prefix = f"РП-{year}-"
            last = (
                IncidentReview.objects.filter(number__startswith=prefix)
                .order_by("-number")
                .first()
            )
            seq = int(last.number.rsplit("-", 1)[-1]) + 1 if last else 1
            self.number = f"{prefix}{seq:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} · {self.title or self.case.title}"

    @property
    def events(self):
        """Простои, входящие в инцидент этого разбора."""
        return self.case.events.all()

    def available_transitions(self):
        """Допустимые переходы статуса для текущего состояния: список (код, надпись на кнопке)."""
        return [
            (target, label)
            for (source, target), label in STATUS_TRANSITIONS.items()
            if source == self.status
        ]


# Какие переходы статуса разрешены и как подписать кнопку.
# Пока (шаг 2) статус меняется вручную. На шаге 5 «Согласовать» станет результатом
# согласования назначенными согласующими.
STATUS_TRANSITIONS = {
    (IncidentReview.Status.DRAFT, IncidentReview.Status.IN_PROGRESS): "В работу",
    (IncidentReview.Status.IN_PROGRESS, IncidentReview.Status.ON_APPROVAL): "На согласование",
    (IncidentReview.Status.ON_APPROVAL, IncidentReview.Status.APPROVED): "Согласовать",
    (IncidentReview.Status.ON_APPROVAL, IncidentReview.Status.REWORK): "Вернуть на доработку",
    (IncidentReview.Status.REWORK, IncidentReview.Status.IN_PROGRESS): "Продолжить",
}


class TimelineEntry(TimeStampedModel):
    """Запись хронологии разбора: когда что произошло (время + текст + автор)."""

    review = models.ForeignKey(
        IncidentReview,
        on_delete=models.CASCADE,
        related_name="timeline",
        verbose_name="Разбор",
    )
    occurred_at = models.DateTimeField("Когда", default=timezone.now)
    text = models.TextField("Запись")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="timeline_entries",
        verbose_name="Автор",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Запись хронологии"
        verbose_name_plural = "Хронология разбора"
        ordering = ["occurred_at", "id"]

    def __str__(self):
        return f"{self.occurred_at:%d.%m.%Y %H:%M} · {self.text[:40]}"


class ReviewLog(TimeStampedModel):
    """История разбора: кто и что менял (создание, смена статуса, правки)."""

    class Action(models.TextChoices):
        CREATED = "created", "Создание"
        STATUS = "status", "Смена статуса"
        UPDATED = "updated", "Изменение"

    review = models.ForeignKey(
        IncidentReview,
        on_delete=models.CASCADE,
        related_name="logs",
        verbose_name="Разбор",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="review_logs",
        verbose_name="Кто",
        null=True,
        blank=True,
    )
    action = models.CharField("Действие", max_length=16, choices=Action.choices)
    comment = models.CharField("Комментарий", max_length=255, blank=True)

    class Meta:
        verbose_name = "Запись истории разбора"
        verbose_name_plural = "История разборов"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_action_display()} · {self.review_id} · {self.created_at:%d.%m.%Y %H:%M}"
