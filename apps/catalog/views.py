"""
Справочники прямо в портале (этап 11.6).

До этого справочники можно было править только в админке Django — это неудобно
для ИТ-службы. Здесь те же действия доступны на обычных страницах портала:

    /catalog/                       — классификация вины ИТ (категория → причина);
    /catalog/category/<pk>/         — правка категории и её причин;
    /catalog/structure/             — производственная структура (цеха);
    /catalog/structure/workshop/<pk>/ — цех: участки и общецеховые агрегаты;
    /catalog/structure/section/<pk>/  — участок: его агрегаты.

Важно: записи **не удаляем** — на них ссылаются исторические простои. Не нужную
категорию/причину/цех/участок/агрегат просто **скрываем** (is_active=False), её можно
вернуть обратно. Это тот же принцип, что и в синхронизации (см. docs/модуль-integrations.md).

Импорт справочников из источника (В9) появится, когда будет доступ к боевой БД; здесь —
**ручное** ведение.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.accounts.decorators import role_required
from apps.accounts.roles import ROLE_ADMIN, ROLE_DOWNTIME_SPECIALIST, ROLE_IT_MANAGER

from .models import (
    ItFaultCategory,
    ItFaultSubcategory,
    Section,
    Unit,
    Workshop,
)

# Кто может вести справочники (те же роли, что и у синхронизации).
CATALOG_ROLES = (ROLE_DOWNTIME_SPECIALIST, ROLE_IT_MANAGER, ROLE_ADMIN)

# Максимальная длина кода и названия — совпадает с полями моделей.
CODE_MAX = 32
NAME_MAX = 255

# Допустимые значения критичности агрегата (для проверки из формы).
CRITICALITY_VALUES = {value for value, _label in Unit.Criticality.choices}


def _clean(value: str) -> str:
    """Обрезает пробелы по краям (в т.ч. неразрывные)."""
    return (value or "").strip()


def _next_subcategory_code(category: ItFaultCategory) -> str:
    """Подбирает следующий свободный код причины внутри категории: «АРМ-01», «АРМ-02»…

    Коды нужны источнику/выгрузкам; пользователю их вводить не обязательно —
    проставляем сами, глядя на уже занятые.
    """
    prefix = category.code
    used = set(
        ItFaultSubcategory.objects.filter(category=category)
        .values_list("code", flat=True)
    )
    index = 1
    while f"{prefix}-{index:02d}" in used:
        index += 1
    return f"{prefix}-{index:02d}"


@login_required
@role_required(*CATALOG_ROLES)
def classification(request):
    """Список категорий вины ИТ (с причинами) и форма добавления новой категории."""
    categories = (
        ItFaultCategory.objects.prefetch_related("subcategories")
        .order_by("-is_active", "name")
    )
    context = {
        "categories": categories,
        "active_count": ItFaultCategory.objects.filter(is_active=True).count(),
        "total_count": ItFaultCategory.objects.count(),
    }
    return render(request, "catalog/classification.html", context)


@login_required
@role_required(*CATALOG_ROLES)
def category_add(request):
    """Добавить категорию (например, новую крупную группу причин)."""
    if request.method != "POST":
        return redirect("catalog:classification")

    code = _clean(request.POST.get("code"))
    name = _clean(request.POST.get("name"))
    description = _clean(request.POST.get("description"))

    if not code or not name:
        messages.error(request, "Укажите код и название категории.")
        return redirect("catalog:classification")
    if len(code) > CODE_MAX or len(name) > NAME_MAX:
        messages.error(request, "Код или название слишком длинные.")
        return redirect("catalog:classification")
    if ItFaultCategory.objects.filter(code=code).exists():
        messages.error(request, f"Категория с кодом «{code}» уже есть.")
        return redirect("catalog:classification")

    category = ItFaultCategory.objects.create(
        code=code, name=name, description=description, is_active=True
    )
    messages.success(request, f"Категория «{category.name}» добавлена.")
    return redirect("catalog:category", pk=category.pk)


@login_required
@role_required(*CATALOG_ROLES)
def category_edit(request, pk):
    """Правка категории: название, описание, показ/скрытие; плюс её причины."""
    category = get_object_or_404(ItFaultCategory, pk=pk)

    if request.method == "POST":
        name = _clean(request.POST.get("name"))
        description = _clean(request.POST.get("description"))
        is_active = request.POST.get("is_active") == "on"

        if not name:
            messages.error(request, "Название не может быть пустым.")
        elif len(name) > NAME_MAX:
            messages.error(request, "Название слишком длинное.")
        else:
            category.name = name
            category.description = description
            category.is_active = is_active
            category.save(update_fields=["name", "description", "is_active", "updated_at"])
            state = "показывается" if is_active else "скрыта"
            messages.success(request, f"Категория «{category.name}» сохранена ({state}).")
        return redirect("catalog:category", pk=category.pk)

    reasons = category.subcategories.order_by("-is_active", "name")
    context = {
        "category": category,
        "reasons": reasons,
        "active_reasons": reasons.filter(is_active=True).count(),
    }
    return render(request, "catalog/category.html", context)


@login_required
@role_required(*CATALOG_ROLES)
def category_toggle(request, pk):
    """Скрыть/вернуть категорию. Не удаляем — на неё ссылаются старые простои."""
    if request.method != "POST":
        return redirect("catalog:classification")

    category = get_object_or_404(ItFaultCategory, pk=pk)
    category.is_active = not category.is_active
    category.save(update_fields=["is_active", "updated_at"])
    if category.is_active:
        messages.success(request, f"Категория «{category.name}» снова показывается.")
    else:
        messages.info(request, f"Категория «{category.name}» скрыта (записи сохранены).")
    return redirect("catalog:classification")


@login_required
@role_required(*CATALOG_ROLES)
def subcategory_add(request, pk):
    """Добавить причину внутрь категории. Код проставляется автоматически."""
    if request.method != "POST":
        return redirect("catalog:classification")

    category = get_object_or_404(ItFaultCategory, pk=pk)
    name = _clean(request.POST.get("name"))
    code = _clean(request.POST.get("code"))

    if not name:
        messages.error(request, "Укажите название причины.")
        return redirect("catalog:category", pk=category.pk)
    if len(name) > NAME_MAX:
        messages.error(request, "Название слишком длинное.")
        return redirect("catalog:category", pk=category.pk)

    # Код можно задать вручную; иначе берём следующий свободный.
    if not code:
        code = _next_subcategory_code(category)
    if len(code) > CODE_MAX:
        messages.error(request, "Код слишком длинный.")
        return redirect("catalog:category", pk=category.pk)
    if ItFaultSubcategory.objects.filter(category=category, code=code).exists():
        messages.error(request, f"Причина с кодом «{code}» в этой категории уже есть.")
        return redirect("catalog:category", pk=category.pk)
    if ItFaultSubcategory.objects.filter(category=category, name=name).exists():
        messages.error(request, f"Причина «{name}» в этой категории уже есть.")
        return redirect("catalog:category", pk=category.pk)

    ItFaultSubcategory.objects.create(
        category=category, code=code, name=name, is_active=True
    )
    messages.success(request, f"Причина «{name}» добавлена в «{category.name}».")
    return redirect("catalog:category", pk=category.pk)


@login_required
@role_required(*CATALOG_ROLES)
def subcategory_edit(request, pk):
    """Переименовать причину и/или скрыть-вернуть её. Код не меняем — на него опираются выгрузки."""
    if request.method != "POST":
        return redirect("catalog:classification")

    reason = get_object_or_404(ItFaultSubcategory, pk=pk)
    name = _clean(request.POST.get("name"))

    if not name:
        messages.error(request, "Название причины не может быть пустым.")
    elif len(name) > NAME_MAX:
        messages.error(request, "Название слишком длинное.")
    elif (
        ItFaultSubcategory.objects.filter(category=reason.category, name=name)
        .exclude(pk=reason.pk)
        .exists()
    ):
        messages.error(request, f"Причина «{name}» в этой категории уже есть.")
    else:
        reason.name = name
        reason.save(update_fields=["name", "updated_at"])
        messages.success(request, "Причина сохранена.")
    return redirect("catalog:category", pk=reason.category_id)


@login_required
@role_required(*CATALOG_ROLES)
def subcategory_toggle(request, pk):
    """Скрыть/вернуть причину. Не удаляем — на неё ссылаются старые простои."""
    if request.method != "POST":
        return redirect("catalog:classification")

    reason = get_object_or_404(ItFaultSubcategory, pk=pk)
    reason.is_active = not reason.is_active
    reason.save(update_fields=["is_active", "updated_at"])
    back = reverse("catalog:category", args=[reason.category_id])
    if reason.is_active:
        messages.success(request, f"Причина «{reason.name}» снова показывается.")
    else:
        messages.info(request, f"Причина «{reason.name}» скрыта (записи сохранены).")
    return redirect(back)


# ---------------------------------------------------------------------------
# Производственная структура: цеха → участки → агрегаты (план Этап 11.6, В9).
# Ручное ведение в портале; импорт из источника — когда будет доступ к боевой БД.
# ---------------------------------------------------------------------------


@login_required
@role_required(*CATALOG_ROLES)
def structure(request):
    """Список цехов (с числом участков и агрегатов) и форма добавления цеха."""
    workshops = (
        Workshop.objects.prefetch_related("sections", "units")
        .order_by("-is_active", "name")
    )
    context = {
        "workshops": workshops,
        "active_count": Workshop.objects.filter(is_active=True).count(),
        "total_count": Workshop.objects.count(),
        "section_count": Section.objects.count(),
        "unit_count": Unit.objects.count(),
    }
    return render(request, "catalog/structure.html", context)


@login_required
@role_required(*CATALOG_ROLES)
def workshop_add(request):
    """Добавить цех."""
    if request.method != "POST":
        return redirect("catalog:structure")

    name = _clean(request.POST.get("name"))
    code = _clean(request.POST.get("code"))

    if not name:
        messages.error(request, "Укажите название цеха.")
        return redirect("catalog:structure")
    if len(name) > NAME_MAX or len(code) > CODE_MAX:
        messages.error(request, "Название или код слишком длинные.")
        return redirect("catalog:structure")
    if Workshop.objects.filter(name=name).exists():
        messages.error(request, f"Цех «{name}» уже есть.")
        return redirect("catalog:structure")

    workshop = Workshop.objects.create(name=name, code=code, is_active=True)
    messages.success(request, f"Цех «{workshop.name}» добавлен.")
    return redirect("catalog:workshop", pk=workshop.pk)


@login_required
@role_required(*CATALOG_ROLES)
def workshop_edit(request, pk):
    """Правка цеха: название, код, показ/скрытие; плюс его участки и общецеховые агрегаты."""
    workshop = get_object_or_404(Workshop, pk=pk)

    if request.method == "POST":
        name = _clean(request.POST.get("name"))
        code = _clean(request.POST.get("code"))
        is_active = request.POST.get("is_active") == "on"

        if not name:
            messages.error(request, "Название не может быть пустым.")
        elif len(name) > NAME_MAX or len(code) > CODE_MAX:
            messages.error(request, "Название или код слишком длинные.")
        elif Workshop.objects.filter(name=name).exclude(pk=workshop.pk).exists():
            messages.error(request, f"Цех «{name}» уже есть.")
        else:
            workshop.name = name
            workshop.code = code
            workshop.is_active = is_active
            workshop.save(update_fields=["name", "code", "is_active", "updated_at"])
            state = "показывается" if is_active else "скрыт"
            messages.success(request, f"Цех сохранён ({state}).")
        return redirect("catalog:workshop", pk=workshop.pk)

    context = {
        "workshop": workshop,
        "sections": workshop.sections.order_by("-is_active", "name"),
        "workshop_units": workshop.units.filter(section__isnull=True).order_by(
            "-is_active", "name"
        ),
        "criticality_choices": Unit.Criticality.choices,
    }
    return render(request, "catalog/workshop.html", context)


@login_required
@role_required(*CATALOG_ROLES)
def workshop_toggle(request, pk):
    """Скрыть/вернуть цех. Не удаляем — на него ссылаются простои."""
    if request.method != "POST":
        return redirect("catalog:structure")

    workshop = get_object_or_404(Workshop, pk=pk)
    workshop.is_active = not workshop.is_active
    workshop.save(update_fields=["is_active", "updated_at"])
    if workshop.is_active:
        messages.success(request, f"Цех «{workshop.name}» снова показывается.")
    else:
        messages.info(request, f"Цех «{workshop.name}» скрыт (записи сохранены).")
    return redirect("catalog:structure")


@login_required
@role_required(*CATALOG_ROLES)
def section_add(request, pk):
    """Добавить участок внутрь цеха."""
    if request.method != "POST":
        return redirect("catalog:structure")

    workshop = get_object_or_404(Workshop, pk=pk)
    name = _clean(request.POST.get("name"))
    code = _clean(request.POST.get("code"))

    if not name:
        messages.error(request, "Укажите название участка.")
        return redirect("catalog:workshop", pk=workshop.pk)
    if len(name) > NAME_MAX or len(code) > CODE_MAX:
        messages.error(request, "Название или код слишком длинные.")
        return redirect("catalog:workshop", pk=workshop.pk)
    if Section.objects.filter(workshop=workshop, name=name).exists():
        messages.error(request, f"Участок «{name}» в этом цехе уже есть.")
        return redirect("catalog:workshop", pk=workshop.pk)

    Section.objects.create(workshop=workshop, name=name, code=code, is_active=True)
    messages.success(request, f"Участок «{name}» добавлен в «{workshop.name}».")
    return redirect("catalog:workshop", pk=workshop.pk)


@login_required
@role_required(*CATALOG_ROLES)
def section_edit(request, pk):
    """Правка участка: название, код, показ/скрытие; плюс его агрегаты."""
    section = get_object_or_404(Section, pk=pk)

    if request.method == "POST":
        name = _clean(request.POST.get("name"))
        code = _clean(request.POST.get("code"))
        is_active = request.POST.get("is_active") == "on"

        if not name:
            messages.error(request, "Название не может быть пустым.")
        elif len(name) > NAME_MAX or len(code) > CODE_MAX:
            messages.error(request, "Название или код слишком длинные.")
        elif (
            Section.objects.filter(workshop=section.workshop, name=name)
            .exclude(pk=section.pk)
            .exists()
        ):
            messages.error(request, f"Участок «{name}» в этом цехе уже есть.")
        else:
            section.name = name
            section.code = code
            section.is_active = is_active
            section.save(update_fields=["name", "code", "is_active", "updated_at"])
            messages.success(request, "Участок сохранён.")
        return redirect("catalog:section", pk=section.pk)

    context = {
        "section": section,
        "units": section.units.order_by("-is_active", "name"),
        "criticality_choices": Unit.Criticality.choices,
    }
    return render(request, "catalog/section.html", context)


@login_required
@role_required(*CATALOG_ROLES)
def section_toggle(request, pk):
    """Скрыть/вернуть участок. Не удаляем — на него ссылаются простои."""
    if request.method != "POST":
        return redirect("catalog:structure")

    section = get_object_or_404(Section, pk=pk)
    section.is_active = not section.is_active
    section.save(update_fields=["is_active", "updated_at"])
    if section.is_active:
        messages.success(request, f"Участок «{section.name}» снова показывается.")
    else:
        messages.info(request, f"Участок «{section.name}» скрыт (записи сохранены).")
    return redirect("catalog:workshop", pk=section.workshop_id)


def _unit_name_taken(name: str, *, section, workshop, exclude_pk=None) -> bool:
    """Проверяет уникальность названия агрегата: на участке — или общецехового — на цехе."""
    query = Unit.objects.filter(name=name)
    if section is not None:
        query = query.filter(section=section)
    else:
        query = query.filter(section__isnull=True, workshop=workshop)
    if exclude_pk is not None:
        query = query.exclude(pk=exclude_pk)
    return query.exists()


def _unit_back(unit: Unit) -> str:
    """Куда вернуться после правки агрегата — на участок или на цех (для общецехового)."""
    if unit.section_id:
        return reverse("catalog:section", args=[unit.section_id])
    return reverse("catalog:workshop", args=[unit.workshop_id])


def _read_unit_form(request):
    """Общие поля агрегата из формы: название, код, критичность."""
    name = _clean(request.POST.get("name"))
    code = _clean(request.POST.get("code"))
    criticality = request.POST.get("criticality", Unit.Criticality.MEDIUM)
    if criticality not in CRITICALITY_VALUES:
        criticality = Unit.Criticality.MEDIUM
    return name, code, criticality


@login_required
@role_required(*CATALOG_ROLES)
def section_unit_add(request, pk):
    """Добавить агрегат на участок."""
    if request.method != "POST":
        return redirect("catalog:structure")

    section = get_object_or_404(Section, pk=pk)
    name, code, criticality = _read_unit_form(request)

    if not name:
        messages.error(request, "Укажите название агрегата.")
    elif len(name) > NAME_MAX or len(code) > CODE_MAX:
        messages.error(request, "Название или код слишком длинные.")
    elif _unit_name_taken(name, section=section, workshop=section.workshop):
        messages.error(request, f"Агрегат «{name}» на этом участке уже есть.")
    else:
        Unit.objects.create(
            section=section, name=name, code=code, criticality=criticality, is_active=True
        )
        messages.success(request, f"Агрегат «{name}» добавлен на участок.")
    return redirect("catalog:section", pk=section.pk)


@login_required
@role_required(*CATALOG_ROLES)
def workshop_unit_add(request, pk):
    """Добавить общецеховой агрегат (без участка) прямо на цех."""
    if request.method != "POST":
        return redirect("catalog:structure")

    workshop = get_object_or_404(Workshop, pk=pk)
    name, code, criticality = _read_unit_form(request)

    if not name:
        messages.error(request, "Укажите название агрегата.")
    elif len(name) > NAME_MAX or len(code) > CODE_MAX:
        messages.error(request, "Название или код слишком длинные.")
    elif _unit_name_taken(name, section=None, workshop=workshop):
        messages.error(request, f"Агрегат «{name}» в этом цехе уже есть.")
    else:
        Unit.objects.create(
            workshop=workshop,
            section=None,
            name=name,
            code=code,
            criticality=criticality,
            is_active=True,
        )
        messages.success(request, f"Общецеховой агрегат «{name}» добавлен в «{workshop.name}».")
    return redirect("catalog:workshop", pk=workshop.pk)


@login_required
@role_required(*CATALOG_ROLES)
def unit_edit(request, pk):
    """Переименовать агрегат и/или сменить критичность. Родитель (участок/цех) не меняется."""
    if request.method != "POST":
        return redirect("catalog:structure")

    unit = get_object_or_404(Unit, pk=pk)
    name, code, criticality = _read_unit_form(request)

    if not name:
        messages.error(request, "Название агрегата не может быть пустым.")
    elif len(name) > NAME_MAX or len(code) > CODE_MAX:
        messages.error(request, "Название или код слишком длинные.")
    elif _unit_name_taken(
        name, section=unit.section, workshop=unit.workshop, exclude_pk=unit.pk
    ):
        messages.error(request, f"Агрегат «{name}» здесь уже есть.")
    else:
        unit.name = name
        unit.code = code
        unit.criticality = criticality
        unit.save(update_fields=["name", "code", "criticality", "updated_at"])
        messages.success(request, "Агрегат сохранён.")
    return redirect(_unit_back(unit))


@login_required
@role_required(*CATALOG_ROLES)
def unit_toggle(request, pk):
    """Скрыть/вернуть агрегат. Не удаляем — на него ссылаются простои."""
    if request.method != "POST":
        return redirect("catalog:structure")

    unit = get_object_or_404(Unit, pk=pk)
    unit.is_active = not unit.is_active
    unit.save(update_fields=["is_active", "updated_at"])
    if unit.is_active:
        messages.success(request, f"Агрегат «{unit.name}» снова показывается.")
    else:
        messages.info(request, f"Агрегат «{unit.name}» скрыт (записи сохранены).")
    return redirect(_unit_back(unit))
