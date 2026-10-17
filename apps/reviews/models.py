"""
Модуль «Разбор простоя» (этап 11.7).

Разбор — это рабочее место по инциденту: хронология, чат, мероприятия и согласование.
Разбор создаётся из одного или нескольких простоев: несколько простоев сначала
объединяются в **инцидент** (он же «кейс», `DowntimeCase`) — так сохраняется правило
«один инцидент = один случай, без двойного счёта». Разбор ссылается на этот инцидент.

Сейчас готовы шаги 1–6: «шапка» разбора (номер, ведущий, статус, связь с инцидентом),
хронология, статусы, участники и чат с упоминаниями, мероприятия, шаблоны, **согласование**
(согласуют все назначенные, можно «вернуть на доработку») и отправка мероприятия тикетом
в **OMNITRACKER** (доп. функция; в разработке — учебный режим).
"""
from django.conf import settings
from django.db import models
from django.db.models import F
from django.utils import timezone

from apps.catalog.models import ItFaultCategory, TimeStampedModel
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
# «На согласование» и «Продолжить» — вручную. Статус «Согласован» ставится
# автоматически, когда **все** назначенные согласующие согласовали (шаг 5),
# а «На доработке» — когда кто-то отклонил.
STATUS_TRANSITIONS = {
    (IncidentReview.Status.DRAFT, IncidentReview.Status.IN_PROGRESS): "В работу",
    (IncidentReview.Status.IN_PROGRESS, IncidentReview.Status.ON_APPROVAL): "На согласование",
    (IncidentReview.Status.REWORK, IncidentReview.Status.IN_PROGRESS): "Продолжить",
}


class ReviewParticipant(TimeStampedModel):
    """Участник разбора: допущен к разбору, может писать в чат.

    `is_approver` используется на шаге согласования: согласуют все назначенные.
    """

    review = models.ForeignKey(
        IncidentReview,
        on_delete=models.CASCADE,
        related_name="participants",
        verbose_name="Разбор",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="review_participations",
        verbose_name="Пользователь",
    )
    is_approver = models.BooleanField("Согласующий", default=False)

    class Meta:
        verbose_name = "Участник разбора"
        verbose_name_plural = "Участники разбора"
        ordering = ["user__username"]
        constraints = [
            models.UniqueConstraint(
                fields=["review", "user"], name="uniq_review_participant"
            ),
        ]

    def __str__(self):
        return f"{self.user} · {self.review.number}"


class ReviewApproval(TimeStampedModel):
    """Решение согласующего по разбору.

    Когда разбор уходит «На согласование», для каждого согласующего создаётся запись
    с решением «ждём». Разбор становится **Согласован** автоматически, когда **все**
    согласующие согласовали. Если кто-то отклонил — разбор уходит «На доработке».
    """

    class Decision(models.TextChoices):
        PENDING = "pending", "Ждём решения"
        APPROVED = "approved", "Согласовано"
        REJECTED = "rejected", "Отклонено (на доработку)"

    review = models.ForeignKey(
        IncidentReview,
        on_delete=models.CASCADE,
        related_name="approvals",
        verbose_name="Разбор",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="review_approvals",
        verbose_name="Согласующий",
    )
    decision = models.CharField(
        "Решение", max_length=16, choices=Decision.choices, default=Decision.PENDING
    )
    comment = models.TextField("Комментарий", blank=True)
    decided_at = models.DateTimeField("Когда решено", null=True, blank=True)

    class Meta:
        verbose_name = "Согласование разбора"
        verbose_name_plural = "Согласования разборов"
        ordering = ["user__username"]
        constraints = [
            models.UniqueConstraint(
                fields=["review", "user"], name="uniq_review_approval"
            ),
        ]

    def __str__(self):
        return f"{self.user} · {self.review.number} · {self.get_decision_display()}"


class ReviewMessage(TimeStampedModel):
    """Сообщение чата разбора. Упоминания — по `@логин`."""

    review = models.ForeignKey(
        IncidentReview,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="Разбор",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="review_messages",
        verbose_name="Автор",
        null=True,
        blank=True,
    )
    text = models.TextField("Сообщение")
    mentions = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="mentioned_in_messages",
        verbose_name="Упоминания",
        blank=True,
    )

    class Meta:
        verbose_name = "Сообщение чата разбора"
        verbose_name_plural = "Сообщения чата разбора"
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.review.number} · {self.author} · {self.created_at:%d.%m.%Y %H:%M}"


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
        APPROVAL = "approval", "Согласование"

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


class ActionTemplate(TimeStampedModel):
    """Шаблон мероприятия: типовое действие по ситуации (категории вины ИТ).

    Справочник: шаблоны **не удаляем**, а скрываем (`is_active=False`) — как категории
    и структуру (см. `модуль-catalog.md`). Шаблон без категории — общий для всех ситуаций.
    """

    category = models.ForeignKey(
        ItFaultCategory,
        on_delete=models.PROTECT,
        related_name="action_templates",
        verbose_name="Категория вины",
        null=True,
        blank=True,
        help_text="Пусто — шаблон общий, подходит для любой ситуации.",
    )
    title = models.CharField("Кратко", max_length=255)
    description = models.TextField("Что сделать", blank=True)
    order = models.PositiveIntegerField("Порядок", default=100)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Шаблон мероприятия"
        verbose_name_plural = "Шаблоны мероприятий"
        ordering = ["order", "title"]

    def __str__(self):
        return f"{self.category.name if self.category else 'Общий'} · {self.title}"


class ReviewAction(TimeStampedModel):
    """Мероприятие по разбору: что сделать, к какому сроку и кто отвечает.

    Ответственных может быть несколько. Статус меняется вручную.
    """

    class Status(models.TextChoices):
        PLANNED = "planned", "Запланировано"
        IN_PROGRESS = "in_progress", "В работе"
        DONE = "done", "Выполнено"
        CANCELED = "canceled", "Отменено"

    review = models.ForeignKey(
        IncidentReview,
        on_delete=models.CASCADE,
        related_name="actions",
        verbose_name="Разбор",
    )
    title = models.CharField("Кратко", max_length=255)
    description = models.TextField("Что сделать", blank=True)
    due_at = models.DateTimeField("Срок", null=True, blank=True)
    assignees = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="review_actions",
        verbose_name="Ответственные",
        blank=True,
    )
    status = models.CharField(
        "Статус", max_length=16, choices=Status.choices, default=Status.PLANNED
    )
    ticket_id = models.CharField("Тикет OMNITRACKER", max_length=128, blank=True)
    ticket_url = models.URLField("Ссылка на тикет", blank=True)
    ticket_group = models.CharField("Группа OMNITRACKER", max_length=128, blank=True)
    ticket_sent_at = models.DateTimeField("Отправлено в OMNITRACKER", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="review_actions_created",
        verbose_name="Создал",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Мероприятие разбора"
        verbose_name_plural = "Мероприятия разбора"
        ordering = [F("due_at").asc(nulls_last=True), "id"]

    def __str__(self):
        return f"{self.review.number} · {self.title}"

    @property
    def is_overdue(self):
        """Срок прошёл, а мероприятие ещё не выполнено и не отменено."""
        if not self.due_at or self.status in (self.Status.DONE, self.Status.CANCELED):
            return False
        return self.due_at < timezone.now()
