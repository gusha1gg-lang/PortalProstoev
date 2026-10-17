"""
Редактор классификации вины ИТ прямо в портале (этап 11.6, инструменты классификации).

До этого категории и причины (2 уровня) можно было править только в админке Django —
это неудобно для ИТ-службы. Здесь те же действия доступны на обычной странице портала:

    /catalog/classification/           — список категорий, добавление новой;
    /catalog/category/<pk>/            — правка категории и её причин.

Важно: записи **не удаляем** — на них ссылаются исторические простои. Не нужную
категорию/причину просто **скрываем** (is_active=False), её можно вернуть обратно.
Это тот же принцип, что и в синхронизации (см. docs/модуль-integrations.md).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.accounts.decorators import role_required
from apps.accounts.roles import ROLE_ADMIN, ROLE_DOWNTIME_SPECIALIST, ROLE_IT_MANAGER

from .models import ItFaultCategory, ItFaultSubcategory

# Кто может вести классификацию вины ИТ (те же роли, что и у синхронизации).
CLASSIFICATION_ROLES = (ROLE_DOWNTIME_SPECIALIST, ROLE_IT_MANAGER, ROLE_ADMIN)

# Максимальная длина кода и названия — совпадает с полями моделей.
CODE_MAX = 32
NAME_MAX = 255


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
@role_required(*CLASSIFICATION_ROLES)
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
@role_required(*CLASSIFICATION_ROLES)
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
@role_required(*CLASSIFICATION_ROLES)
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
@role_required(*CLASSIFICATION_ROLES)
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
@role_required(*CLASSIFICATION_ROLES)
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
@role_required(*CLASSIFICATION_ROLES)
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
@role_required(*CLASSIFICATION_ROLES)
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
