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
