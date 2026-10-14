"""
Справочники портала: производственная структура, категории вины ИТ, ставки потерь.

Здесь только структура данных (модели = таблицы в БД). Логика расчётов — в модуле sla.
"""
from django.db import models


class TimeStampedModel(models.Model):
    """Общая база: хранит дату создания и последнего изменения записи."""

    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    class Meta:
        abstract = True


class Workshop(TimeStampedModel):
    """Цех — верхний уровень производственной структуры."""

    code = models.CharField("Код", max_length=32, unique=True)
    name = models.CharField("Название", max_length=255)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Цех"
        verbose_name_plural = "Цеха"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class ProductionLine(TimeStampedModel):
    """Производственная линия внутри цеха."""

    workshop = models.ForeignKey(
        Workshop, on_delete=models.PROTECT, related_name="lines", verbose_name="Цех"
    )
    code = models.CharField("Код", max_length=32)
    name = models.CharField("Название", max_length=255)
    is_active = models.BooleanField("Активна", default=True)

    class Meta:
        verbose_name = "Линия"
        verbose_name_plural = "Линии"
        ordering = ["workshop__name", "name"]
        # Код линии уникален в пределах цеха.
        constraints = [
            models.UniqueConstraint(fields=["workshop", "code"], name="uniq_line_code_per_workshop")
        ]

    def __str__(self):
        return f"{self.workshop.code} / {self.name}"


class Equipment(TimeStampedModel):
    """Оборудование (агрегат) на линии."""

    class Criticality(models.TextChoices):
        CRITICAL = "critical", "Особо важное"
        HIGH = "high", "Высокая"
        MEDIUM = "medium", "Средняя"
        LOW = "low", "Низкая"

    line = models.ForeignKey(
        ProductionLine, on_delete=models.PROTECT, related_name="equipment", verbose_name="Линия"
    )
    code = models.CharField("Код", max_length=32)
    name = models.CharField("Название", max_length=255)
    criticality = models.CharField(
        "Критичность", max_length=16, choices=Criticality.choices, default=Criticality.MEDIUM
    )
    is_active = models.BooleanField("Активно", default=True)

    class Meta:
        verbose_name = "Оборудование"
        verbose_name_plural = "Оборудование"
        ordering = ["line__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["line", "code"], name="uniq_equipment_code_per_line")
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class ItFaultCategory(TimeStampedModel):
    """Категория вины ИТ: сеть, серверы, ПО, интеграции, БД и т.д."""

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
    """Подкатегория вины ИТ внутри категории."""

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
    Ставка потерь по линии. Версионируется по датам: для события берётся
    ставка, действовавшая на дату простоя.
    """

    line = models.ForeignKey(
        ProductionLine, on_delete=models.PROTECT, related_name="loss_rates", verbose_name="Линия"
    )
    cost_per_hour = models.DecimalField("Потери за час, ₽", max_digits=14, decimal_places=2)
    ton_margin = models.DecimalField("Маржа за тонну, ₽", max_digits=14, decimal_places=2, default=0)
    valid_from = models.DateField("Действует с")
    valid_to = models.DateField("Действует по", null=True, blank=True)
    note = models.CharField("Примечание", max_length=255, blank=True)

    class Meta:
        verbose_name = "Ставка потерь"
        verbose_name_plural = "Ставки потерь"
        ordering = ["line__name", "-valid_from"]
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
        return f"{self.line.name}: {self.cost_per_hour} ₽/ч ({period})"
