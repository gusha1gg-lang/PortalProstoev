"""Команда наполнения справочников реальными данными (из выгрузки заказчика).

Запуск:  python manage.py seed_catalog
Идемпотентна: повторный запуск не создаёт дублей.

Опознаём записи по НАЗВАНИЮ (кодов в источнике нет).
Список цехов/объектов — получен от заказчика (верхний уровень структуры).
Детально (участки, агрегаты, ставки) наполняется только ТЭСЦ-4 — по данным выгрузки Excel.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.catalog.models import (
    ItFaultCategory,
    ItFaultSubcategory,
    LossRate,
    Section,
    Unit,
    Workshop,
)

# Цеха и объекты (в том виде, как в источнике; уровень «Предприятие» убран).
WORKSHOPS = [
    # Цеха ТЭСЦ и прочие объекты завода.
    "КПЦ ДЖДК",
    "ЛПК",
    "МКС-5000",
    "Спецтехника",
    "СПЦ ДЖДК",
    "ТПЦ",
    "ТЭСЦ-1",
    "ТЭСЦ-2",
    "ТЭСЦ-3",
    "ТЭСЦ-4",
    "ТЭСЦ-5",
    "ЦАПТ",
    "ЦЗЛ",
    "ЦПМ",
    # Подразделения (в виде, как они называются в источнике).
    "Юрьевец",
    "Юрьев-Польский",
    "Вязники",
    "Гусь-Хрустальный",
    "Киржач",
    "Ковров",
    "Кольчугино",
    "Арзамас ВФ",
    "Дзержинский ВФ",
    "Мотмос",
    "Муром",
    "УБСС",
    "Мытищи",
    "Шереметьево",
    "Щелмет",
    "Волгореченский",
    "КРЦ",
    "МРЦ",
    "АТЗ ТЭСЦ-1",
    "АТЗ ТЭСЦ-2",
    "ЭМК",
]

# Детально наполняем только ТЭСЦ-4 (реальные данные из выгрузки).
# Ключ: цех -> список участков.
SECTIONS = {
    "ТЭСЦ-4": [
        "Участок отделки труб 1020",
        "Участок сварки труб 1020",
        "Участок формовки труб 1020",
        "Участок ремонта и гидроиспытаний 1020",
    ],
}

# Ключ: (цех, участок) -> список (агрегат, критичность).
UNITS = {
    ("ТЭСЦ-4", "Участок отделки труб 1020"): [
        ("Площадка №9 окончательной приемки — ОПТ №9", "high"),
        ("Участок АУЗК-31 — АУЗК-31", "medium"),
    ],
    ("ТЭСЦ-4", "Участок сварки труб 1020"): [
        ("Ремонтная площадка №3 — ССС-3", "high"),
    ],
    ("ТЭСЦ-4", "Участок формовки труб 1020"): [
        ("Участок клеймовки и накопителя — Участок клеймения труб", "high"),
    ],
    ("ТЭСЦ-4", "Участок ремонта и гидроиспытаний 1020"): [
        ("Участок гидропресса №2 — П9046-2", "critical"),
    ],
}

# Общецеховые агрегаты (без участка) — крепятся прямо к цеху (question.md, В1).
WORKSHOP_UNITS = {
    "ТЭСЦ-4": [
        ("Компрессорная цеха", "high"),
        ("Подстанция цеха", "critical"),
    ],
}

# Реальная классификация вины ИТ (2 уровня: категория -> причина).
# Источник — файл руководителя, см. question.md, В3. Ведём её сами (правим в админке/портале).
CATEGORIES = [
    ("ARM", "АРМ"),
    ("INFRA", "Инфраструктура"),
    ("CIS", "ЦИС"),
    ("KIS", "КИС"),
    ("NOTIT", "Не наша ИТ-служба"),
]

# Категория -> список причин (подкатегорий). Коды причин проставляем автоматически:
# ARM-01, ARM-02 и т.д. Опознаём причины по НАЗВАНИЮ внутри категории.
SUBCATEGORIES = {
    "ARM": [
        "Аппаратная неисправность",
        "Действия пользователей",
        "Настройки ПО",
        "Настройки оборудования",
        "Неизвестно",
        "Быстродействие АРМ",
        "Расходники",
        "Обновление базового ПО",
        "Сбой базового ПО",
        "Учетные данные пользователя",
        "Электропитание",
        "Блокировка АВПО",
        "Действия специалистов ИТ-службы",
    ],
    "INFRA": [
        "Аппаратная неисправность",
        "Блокировки данных в БД",
        "Блокировки МЭ",
        "Сбой ПО",
        "Быстродействие ИТ-инфраструктуры",
        "Технические работы",
        "Электропитание",
        "Сбой связи/соединения",
        "Действия специалистов ИТ-службы",
        "Настройки ПО",
        "Неизвестно",
    ],
    "CIS": [
        "Действия пользователей",
        "Бизнес-логика ПО",
        "Доработки/обновление ЦИС",
        "Действия специалистов ИТ-службы",
        "Программный сбой",
        "Настройки ЦИС",
        "Неизвестно",
        "Некорректные данные",
        "Учетные данные пользователя",
        "Технические работы",
        "Быстродействие ЦИС",
    ],
    "KIS": [
        "Действия пользователей",
        "Действия специалистов ИТ-службы",
        "Неизвестно",
        "Технические работы",
        "Доработки/обновление КИС",
        "Программный сбой",
    ],
    "NOTIT": [
        "Действия пользователей",
        "Неизвестно",
        "Аппаратная неисправность",
        "Настройки оборудования/ПО",
        "Программный сбой",
    ],
}

# Старая (учебная) классификация. Не удаляем — на неё могут ссылаться исторические
# простои, — а помечаем неактивной. См. question.md, В3.
OLD_CATEGORY_CODES = ["NET", "SRV", "APP", "INT", "DBA", "SEC", "HUM"]

# Ключ: (цех, участок) -> потери за час, ₽.
RATES = {
    ("ТЭСЦ-4", "Участок отделки труб 1020"): Decimal("120000.00"),
    ("ТЭСЦ-4", "Участок сварки труб 1020"): Decimal("90000.00"),
    ("ТЭСЦ-4", "Участок формовки труб 1020"): Decimal("120000.00"),
    ("ТЭСЦ-4", "Участок ремонта и гидроиспытаний 1020"): Decimal("150000.00"),
}


class Command(BaseCommand):
    help = "Создаёт справочники (цеха, участки, агрегаты, категории вины, ставки)."

    def handle(self, *args, **options):
        for name in WORKSHOPS:
            Workshop.objects.get_or_create(name=name)

        for workshop_name, section_names in SECTIONS.items():
            workshop = Workshop.objects.get(name=workshop_name)
            for name in section_names:
                Section.objects.get_or_create(workshop=workshop, name=name)

        for (workshop_name, section_name), units in UNITS.items():
            section = Section.objects.get(workshop__name=workshop_name, name=section_name)
            for name, criticality in units:
                Unit.objects.get_or_create(
                    section=section, name=name, defaults={"criticality": criticality}
                )

        for workshop_name, units in WORKSHOP_UNITS.items():
            workshop = Workshop.objects.get(name=workshop_name)
            for name, criticality in units:
                Unit.objects.get_or_create(
                    workshop=workshop,
                    section=None,
                    name=name,
                    defaults={"criticality": criticality},
                )

        for code, name in CATEGORIES:
            ItFaultCategory.objects.update_or_create(
                code=code, defaults={"name": name, "is_active": True}
            )

        for category_code, reasons in SUBCATEGORIES.items():
            category = ItFaultCategory.objects.get(code=category_code)
            for index, name in enumerate(reasons, start=1):
                ItFaultSubcategory.objects.get_or_create(
                    category=category,
                    name=name,
                    defaults={"code": f"{category_code}-{index:02d}", "is_active": True},
                )

        # Старую классификацию оставляем в базе, но скрываем.
        ItFaultCategory.objects.filter(code__in=OLD_CATEGORY_CODES).update(is_active=False)
        ItFaultSubcategory.objects.filter(category__code__in=OLD_CATEGORY_CODES).update(is_active=False)

        for (workshop_name, section_name), cost in RATES.items():
            section = Section.objects.get(workshop__name=workshop_name, name=section_name)
            LossRate.objects.get_or_create(
                section=section,
                valid_from="2025-01-01",
                defaults={"cost_per_hour": cost, "note": "Демо-ставка"},
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Справочники заполнены: цеха={Workshop.objects.count()}, "
                f"участки={Section.objects.count()}, агрегаты={Unit.objects.count()}."
            )
        )
