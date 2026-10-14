"""
Справочники портала: производственная структура, категории вины ИТ, ставки потерь.

Названия соответствуют реальным терминам предприятия:
    Предприятие (Enterprise) -> Цех (Workshop) -> Участок (Section) -> Агрегат (Unit).

Портал обслуживает всю группу ОМК (много заводов, дивизионов и депо по России).
Здесь только структура данных (модели = таблицы в БД). Логика расчётов — в модуле sla.
"""
from django.db import models


class TimeStampedModel(models.Model):
    """Общая база: хранит дату создания и последнего изменения записи."""

    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    class Meta:
        abstract = True


class Enterprise(TimeStampedModel):
    """Предприятие / завод / дивизион / депо группы ОМК — верхний уровень структуры."""

    code = models.CharField("Код", max_length=32, unique=True)
    name = models.CharField("Название", max_length=255)
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
    code = models.CharField("Код", max_length=32)
    name = models.CharField("Название", max_length=255)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Цех"
        verbose_name_plural = "Цеха"
        ordering = ["enterprise__name", "name"]
        # Код цеха уникален в пределах предприятия.
        constraints = [
            models.UniqueConstraint(fields=["enterprise", "code"], name="uniq_workshop_code_per_enterprise")
        ]

    def __str__(self):
        return f"{self.enterprise.name} / {self.name}"


class Section(TimeStampedModel):
    """Участок внутри цеха."""

    workshop = models.ForeignKey(
        Workshop, on_delete=models.PROTECT, related_name="sections", verbose_name="Цех"
    )
    code = models.CharField("Код", max_length=32)
    name = models.CharField("Название", max_length=255)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Участок"
        verbose_name_plural = "Участки"
        ordering = ["workshop__name", "name"]
        # Код участка уникален в пределах цеха.
        constraints = [
            models.UniqueConstraint(fields=["workshop", "code"], name="uniq_section_code_per_workshop")
        ]

    def __str__(self):
        return f"{self.workshop.code} / {self.name}"


class Unit(TimeStampedModel):
    """Агрегат (единица оборудования) на участке."""

    class Criticality(models.TextChoices):
        CRITICAL = "critical", "Особо важный"
        HIGH = "high", "Высокая"
        MEDIUM = "medium", "Средняя"
        LOW = "low", "Низкая"

    section = models.ForeignKey(
        Section, on_delete=models.PROTECT, related_name="units", verbose_name="Участок"
    )
    code = models.CharField("Код", max_length=32)
    name = models.CharField("Название", max_length=255)
    criticality = models.CharField(
        "Критичность", max_length=16, choices=Criticality.choices, default=Criticality.MEDIUM
    )
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Агрегат"
        verbose_name_plural = "Агрегаты"
        ordering = ["section__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["section", "code"], name="uniq_unit_code_per_section")
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
    Ставка потерь по участку. Версионируется по датам: для события берётся
    ставка, действовавшая на дату простоя.
    """

    section = models.ForeignKey(
        Section, on_delete=models.PROTECT, related_name="loss_rates", verbose_name="Участок"
    )
    cost_per_hour = models.DecimalField("Потери за час, ₽", max_digits=14, decimal_places=2)
    ton_margin = models.DecimalField("Маржа за тонну, ₽", max_digits=14, decimal_places=2, default=0)
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
