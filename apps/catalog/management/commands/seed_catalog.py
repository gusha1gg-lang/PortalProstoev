"""Команда наполнения справочников реальными данными (из выгрузки заказчика).

Запуск:  python manage.py seed_catalog
Идемпотентна: повторный запуск не создаёт дублей.

Опознаём записи по НАЗВАНИЮ (кодов в источнике нет).
Список предприятий/цехов — получен от заказчика (выпадающий список сайта).
Детально (участки, агрегаты, ставки) наполняется только ТЭСЦ-4 — по данным выгрузки Excel.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.catalog.models import (
    Enterprise,
    ItFaultCategory,
    ItFaultSubcategory,
    LossRate,
    Section,
    Unit,
    Workshop,
)

# Предприятия группы ОМК (в том виде, как в источнике).
ENTERPRISES = [
    'АО "ВМЗ"',
    'ВлФ "МК ОМК-ЭкоМеталл"',
    'ВФ "МК ОМК-ЭкоМеталл"',
    'МрФ "МК ОМК-ЭкоМеталл"',
    "Волгореченский завод",
    'ООО "ВМЗ-Техно"',
    "Филиал ВМЗ в г. Альметьевск",
    "Экоплант",
]

# Предприятие -> список цехов/объектов.
WORKSHOPS = {
    'АО "ВМЗ"': [
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
    ],
    'ВлФ "МК ОМК-ЭкоМеталл"': [
        "Юрьевец",
        "Юрьев-Польский",
        "Вязники",
        "Гусь-Хрустальный",
        "Киржач",
        "Ковров",
        "Кольчугино",
    ],
    'ВФ "МК ОМК-ЭкоМеталл"': [
        "Арзамас ВФ",
        "Дзержинский ВФ",
        "Мотмос",
        "Муром",
        "УБСС",
    ],
    'МрФ "МК ОМК-ЭкоМеталл"': [
        "Мытищи",
        "Шереметьево",
        "Щелмет",
    ],
    "Волгореченский завод": [
        "Волгореченский",
    ],
    'ООО "ВМЗ-Техно"': [
        "КРЦ",
        "МРЦ",
    ],
    "Филиал ВМЗ в г. Альметьевск": [
        "АТЗ ТЭСЦ-1",
        "АТЗ ТЭСЦ-2",
    ],
    "Экоплант": [
        "ЭМК",
    ],
}

# Детально наполняем только ТЭСЦ-4 (реальные данные из выгрузки).
# Ключ: (предприятие, цех) -> список участков.
SECTIONS = {
    ('АО "ВМЗ"', "ТЭСЦ-4"): [
        "Участок отделки труб 1020",
        "Участок сварки труб 1020",
        "Участок формовки труб 1020",
        "Участок ремонта и гидроиспытаний 1020",
    ],
}

# Ключ: (предприятие, цех, участок) -> список (агрегат, критичность).
UNITS = {
    ('АО "ВМЗ"', "ТЭСЦ-4", "Участок отделки труб 1020"): [
        ("Площадка №9 окончательной приемки — ОПТ №9", "high"),
        ("Участок АУЗК-31 — АУЗК-31", "medium"),
    ],
    ('АО "ВМЗ"', "ТЭСЦ-4", "Участок сварки труб 1020"): [
        ("Ремонтная площадка №3 — ССС-3", "high"),
    ],
    ('АО "ВМЗ"', "ТЭСЦ-4", "Участок формовки труб 1020"): [
        ("Участок клеймовки и накопителя — Участок клеймения труб", "high"),
    ],
    ('АО "ВМЗ"', "ТЭСЦ-4", "Участок ремонта и гидроиспытаний 1020"): [
        ("Участок гидропресса №2 — П9046-2", "critical"),
    ],
}

# Общецеховые агрегаты (без участка) — крепятся прямо к цеху (question.md, В1).
WORKSHOP_UNITS = {
    ('АО "ВМЗ"', "ТЭСЦ-4"): [
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

# Ключ: (предприятие, цех, участок) -> потери за час, ₽.
RATES = {
    ('АО "ВМЗ"', "ТЭСЦ-4", "Участок отделки труб 1020"): Decimal("120000.00"),
    ('АО "ВМЗ"', "ТЭСЦ-4", "Участок сварки труб 1020"): Decimal("90000.00"),
    ('АО "ВМЗ"', "ТЭСЦ-4", "Участок формовки труб 1020"): Decimal("120000.00"),
    ('АО "ВМЗ"', "ТЭСЦ-4", "Участок ремонта и гидроиспытаний 1020"): Decimal("150000.00"),
}


class Command(BaseCommand):
    help = "Создаёт справочники (предприятия, цеха, участки, агрегаты, категории вины, ставки)."

    def handle(self, *args, **options):
        for name in ENTERPRISES:
            Enterprise.objects.get_or_create(name=name)

        for enterprise_name, workshop_names in WORKSHOPS.items():
            enterprise = Enterprise.objects.get(name=enterprise_name)
            for name in workshop_names:
                Workshop.objects.get_or_create(enterprise=enterprise, name=name)

        for (enterprise_name, workshop_name), section_names in SECTIONS.items():
            workshop = Workshop.objects.get(enterprise__name=enterprise_name, name=workshop_name)
            for name in section_names:
                Section.objects.get_or_create(workshop=workshop, name=name)

        for (enterprise_name, workshop_name, section_name), units in UNITS.items():
            section = Section.objects.get(
                workshop__enterprise__name=enterprise_name,
                workshop__name=workshop_name,
                name=section_name,
            )
            for name, criticality in units:
                Unit.objects.get_or_create(
                    section=section, name=name, defaults={"criticality": criticality}
                )

        for (enterprise_name, workshop_name), units in WORKSHOP_UNITS.items():
            workshop = Workshop.objects.get(enterprise__name=enterprise_name, name=workshop_name)
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

        for (enterprise_name, workshop_name, section_name), cost in RATES.items():
            section = Section.objects.get(
                workshop__enterprise__name=enterprise_name,
                workshop__name=workshop_name,
                name=section_name,
            )
            LossRate.objects.get_or_create(
                section=section,
                valid_from="2025-01-01",
                defaults={"cost_per_hour": cost, "note": "Демо-ставка"},
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Справочники заполнены: предприятия={Enterprise.objects.count()}, "
                f"цеха={Workshop.objects.count()}, участки={Section.objects.count()}, "
                f"агрегаты={Unit.objects.count()}."
            )
        )
