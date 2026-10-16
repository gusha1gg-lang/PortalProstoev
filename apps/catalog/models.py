"""
Справочники портала: производственная структура, категории вины ИТ, ставки потерь.

Названия соответствуют реальным терминам предприятия:
    Предприятие (Enterprise) -> Цех (Workshop) -> Участок (Section) -> Агрегат (Unit).
Агрегат может быть общецеховым — без участка (тогда он крепится прямо к цеху, см. question.md, В1).

Портал обслуживает всю группу ОМК (много заводов, дивизионов и депо по России).
Здесь только структура данных (модели = таблицы в БД). Логика расчётов — в модуле sla.
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class TimeStampedModel(models.Model):
    """Общая база: хранит дату создания и последнего изменения записи."""

    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    class Meta:
        abstract = True


class Enterprise(TimeStampedModel):
    """Предприятие / завод / филиал группы ОМК — верхний уровень структуры."""

    name = models.CharField("Название", max_length=255, unique=True)
    code = models.CharField("Код (если есть)", max_length=32, blank=True)
    is_active = models.BooleanField("Активно", default=True)

    class Meta:
        verbose_name = "Предприятие"
        verbose_name_plural = "Предприятия"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Workshop(TimeStampedModel):
    """Цех (или объект) внутри предприятия."""

    enterprise = models.ForeignKey(
        Enterprise, on_delete=models.PROTECT, related_name="workshops", verbose_name="Предприятие"
    )
    name = models.CharField("Название", max_length=255)
    code = models.CharField("Код (если есть)", max_length=32, blank=True)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Цех"
        verbose_name_plural = "Цеха"
        ordering = ["enterprise__name", "name"]
        # Название цеха уникально в пределах предприятия.
        constraints = [
            models.UniqueConstraint(fields=["enterprise", "name"], name="uniq_workshop_name_per_enterprise")
        ]

    def __str__(self):
        return f"{self.enterprise.name} / {self.name}"


class Section(TimeStampedModel):
    """Участок внутри цеха."""

    workshop = models.ForeignKey(
        Workshop, on_delete=models.PROTECT, related_name="sections", verbose_name="Цех"
    )
    name = models.CharField("Название", max_length=255)
    code = models.CharField("Код (если есть)", max_length=32, blank=True)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Участок"
        verbose_name_plural = "Участки"
        ordering = ["workshop__name", "name"]
        # Название участка уникально в пределах цеха.
        constraints = [
            models.UniqueConstraint(fields=["workshop", "name"], name="uniq_section_name_per_workshop")
        ]

    def __str__(self):
        return f"{self.workshop.name} / {self.name}"


class Unit(TimeStampedModel):
    """Агрегат (единица оборудования). Обычно на участке; бывает общецеховой — прямо на цехе."""

    class Criticality(models.TextChoices):
        CRITICAL = "critical", "Особо важный"
        HIGH = "high", "Высокая"
        MEDIUM = "medium", "Средняя"
        LOW = "low", "Низкая"

    workshop = models.ForeignKey(
        Workshop,
        on_delete=models.PROTECT,
        related_name="units",
        verbose_name="Цех",
        null=True,
        blank=True,
    )
    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="units",
        verbose_name="Участок",
        null=True,
        blank=True,
    )
    name = models.CharField("Название", max_length=255)
    code = models.CharField("Код (если есть)", max_length=32, blank=True)
    criticality = models.CharField(
        "Критичность", max_length=16, choices=Criticality.choices, default=Criticality.MEDIUM
    )
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Агрегат"
        verbose_name_plural = "Агрегаты"
        ordering = ["workshop__name", "section__name", "name"]
        constraints = [
            # Название агрегата уникально в пределах участка…
            models.UniqueConstraint(fields=["section", "name"], name="uniq_unit_name_per_section"),
            # …а для общецеховых (без участка) — в пределах цеха.
            models.UniqueConstraint(
                fields=["workshop", "name"],
                condition=Q(section__isnull=True),
                name="uniq_unit_name_per_workshop_without_section",
            ),
        ]

    def clean(self):
        """Цех обязателен; если задан участок — цех должен совпадать с его цехом."""
        if self.section_id is None and self.workshop_id is None:
            raise ValidationError({"workshop": "Укажите цех или участок."})
        if self.section_id and self.workshop_id and self.section.workshop_id != self.workshop_id:
            raise ValidationError({"section": "Участок относится к другому цеху."})

    def save(self, *args, **kwargs):
        """Цех всегда выводим из участка, если участок задан."""
        if self.section_id:
            self.workshop_id = self.section.workshop_id
        super().save(*args, **kwargs)

    def __str__(self):
        code = f" ({self.code})" if self.code else ""
        return f"{self.name}{code}"


class ItFaultCategory(TimeStampedModel):
    """Категория вины ИТ: АРМ, Инфраструктура, ЦИС, КИС, «Не наша ИТ-служба» (см. question.md, В3)."""

    code = models.CharField("Код", max_length=32, unique=True)
    name = models.CharField("Название", max_length=255)
    description = models.TextField("Описание", blank=True)
    is_active = models.BooleanField("Активна", default=True)

    class Meta:
        verbose_name = "Категория вины ИТ"
        verbose_name_plural = "Категории вины ИТ"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ItFaultSubcategory(TimeStampedModel):
    """Причина (подкатегория) вины ИТ внутри категории."""

    category = models.ForeignKey(
        ItFaultCategory, on_delete=models.PROTECT, related_name="subcategories", verbose_name="Категория"
    )
    code = models.CharField("Код", max_length=32)
    name = models.CharField("Название", max_length=255)
    is_active = models.BooleanField("Активна", default=True)

    class Meta:
        verbose_name = "Подкатегория вины ИТ"
        verbose_name_plural = "Подкатегории вины ИТ"
        ordering = ["category__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["category", "code"], name="uniq_subcategory_code_per_category")
        ]

    def __str__(self):
        return f"{self.category.name} / {self.name}"


class LossRate(TimeStampedModel):
    """
    Ставка потерь по участку. Версионируется по датам: для события берётся
    ставка, действовавшая на дату простоя.
    """

    section = models.ForeignKey(
        Section, on_delete=models.PROTECT, related_name="loss_rates", verbose_name="Участок"
    )
    cost_per_hour = models.DecimalField("Потери за час, ₽", max_digits=14, decimal_places=2)
    valid_from = models.DateField("Действует с")
    valid_to = models.DateField("Действует по", null=True, blank=True)
    note = models.CharField("Примечание", max_length=255, blank=True)

    class Meta:
        verbose_name = "Ставка потерь"
        verbose_name_plural = "Ставки потерь"
        ordering = ["section__name", "-valid_from"]
        constraints = [
            # Дата начала не может быть позже даты окончания.
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=models.F("valid_from")),
                name="loss_rate_valid_to_after_from",
            )
        ]

    def __str__(self):
        period = f"с {self.valid_from}"
        if self.valid_to:
            period += f" по {self.valid_to}"
        return f"{self.section.name}: {self.cost_per_hour} ₽/ч ({period})"
