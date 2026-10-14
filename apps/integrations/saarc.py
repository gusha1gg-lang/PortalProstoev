"""
Адаптер источника простоев — СААРЦ.

СААРЦ — «Система автоматизированного анализа работы цеха», собственная разработка ОМК.
Она собирает данные с производственного оборудования, в том числе простои. Мы их только
ЧИТАЕМ (SELECT), ничего не меняем: портал не «собирает» простои сам, а фильтрует их из
СААРЦ и приводит к удобному для ИТ виду.

Как это устроено:
    BaseSaarcSource  — общий «портрет» источника (что умеет).
    MockSaarcSource  — заглушка для разработки (встроенные строки-примеры).
    LiveSaarcSource  — реальная база СААРЦ (драйвер подключается лениво).

Выбор реализации — в factory.py по флагу INTEGRATION_MODE из .env.

СУБД СААРЦ пока уточняется (question.md, В46). Сейчас код рассчитан на Oracle и использует
драйвер python-oracledb; при другой СУБД меняется только LiveSaarcSource.
"""
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings

# Ответственная служба «наша» — простои по вине ИТ-компании (прежнее название ОМК-ИТ).
DIT_SERVICE = "ДИТ"


class SaarcSourceError(RuntimeError):
    """Понятная ошибка при проблемах с реальным источником СААРЦ."""


@dataclass
class SourceRow:
    """Одна строка источника в том виде, как её отдаёт СААРЦ (русские колонки)."""

    data: dict

    def get(self, key, default=""):
        value = self.data.get(key, default)
        return default if value is None else value


class BaseSaarcSource:
    """Общий интерфейс источника простоев."""

    def fetch_rows(self, since=None, until=None) -> list[SourceRow]:
        """Возвращает строки простоев (все службы — фильтр по ДИТ делается при импорте)."""
        raise NotImplementedError


# --- Мок-данные (для разработки без СААРЦ) ---
# Специально в формате источника: русские колонки, длительность текстом, есть дубли,
# строка чужой службы и строка с незнакомым цехом — чтобы проверить фильтр и отчёт.
MOCK_ROWS = [
    {
        "НАЧАЛО": "2026-09-20 10:00:12",
        "КОНЕЦ": "2026-09-20 10:20:40",
        "ДЛИТЕЛЬНОСТЬ": "0ч.20мин.",
        "ПРИЧИНА": "",
        "ПРИМЕЧАНИЕ": "Отказ сервера приложений",
        "АГГРЕГАТ": "Площадка №9 окончательной приемки — ОПТ №9",
        "УЧАСТОК": "Участок отделки труб 1020",
        "ФИО": "Иванов И.И.",
        "СЛУЖБА": "ДИТ",
        "ЦЕХ": "ТЭСЦ-4",
    },
    {
        "НАЧАЛО": "2026-09-20 10:00:15",
        "КОНЕЦ": "2026-09-20 10:20:40",
        "ДЛИТЕЛЬНОСТЬ": "0ч.20мин.",
        "ПРИЧИНА": "",
        "ПРИМЕЧАНИЕ": "Отказ сервера приложений",
        "АГГРЕГАТ": "Участок АУЗК-31 — АУЗК-31",
        "УЧАСТОК": "Участок отделки труб 1020",
        "ФИО": "Петров П.П.",
        "СЛУЖБА": "ДИТ",
        "ЦЕХ": "ТЭСЦ-4",
    },
    {
        "НАЧАЛО": "2026-09-20 10:01:00",
        "КОНЕЦ": "2026-09-20 10:20:40",
        "ДЛИТЕЛЬНОСТЬ": "0ч.19мин.",
        "ПРИЧИНА": "",
        "ПРИМЕЧАНИЕ": "Отказ сервера приложений",
        "АГГРЕГАТ": "Ремонтная площадка №3 — ССС-3",
        "УЧАСТОК": "Участок сварки труб 1020",
        "ФИО": "Сидоров С.С.",
        "СЛУЖБА": "ДИТ",
        "ЦЕХ": "ТЭСЦ-4",
    },
    {
        # Чужая служба — должна отфильтроваться при импорте.
        "НАЧАЛО": "2026-09-20 11:00:00",
        "КОНЕЦ": "2026-09-20 11:30:00",
        "ДЛИТЕЛЬНОСТЬ": "0ч.30мин.",
        "ПРИЧИНА": "",
        "ПРИМЕЧАНИЕ": "Ремонт крана",
        "АГГРЕГАТ": "",
        "УЧАСТОК": "",
        "ФИО": "Кузнецов К.К.",
        "СЛУЖБА": "Энергоцех",
        "ЦЕХ": "ТЭСЦ-4",
    },
    {
        # ДИТ, но цех незнаком — должна пропуститься с отметкой в отчёте.
        "НАЧАЛО": "2026-09-21 09:00:00",
        "КОНЕЦ": "2026-09-21 09:15:00",
        "ДЛИТЕЛЬНОСТЬ": "0ч.15мин.",
        "ПРИЧИНА": "",
        "ПРИМЕЧАНИЕ": "Нет связи с АСУ",
        "АГГРЕГАТ": "",
        "УЧАСТОК": "",
        "ФИО": "Орлов О.О.",
        "СЛУЖБА": "ДИТ",
        "ЦЕХ": "НЕИЗВЕСТНЫЙ ЦЕХ",
    },
]


class MockSaarcSource(BaseSaarcSource):
    """Заглушка: отдаёт встроенные строки. Работает без СААРЦ и без драйвера."""

    def fetch_rows(self, since=None, until=None) -> list[SourceRow]:
        rows = [SourceRow(dict(row)) for row in MOCK_ROWS]
        if since or until:
            rows = [row for row in rows if _in_period(row.get("НАЧАЛО"), since, until)]
        return rows


class LiveSaarcSource(BaseSaarcSource):
    """Реальная база СААРЦ. Драйвер подключается только при вызове (лениво)."""

    def fetch_rows(self, since=None, until=None) -> list[SourceRow]:
        try:
            import oracledb  # noqa: F401  (импорт внутри метода — чтобы mock работал без драйвера)
        except ImportError as exc:
            raise SaarcSourceError(
                "Не установлен драйвер python-oracledb (нужен только для live-режима). "
                "Установите: pip install python-oracledb"
            ) from exc

        if not settings.SAARC_USER or not settings.SAARC_DSN:
            raise SaarcSourceError("Не заданы SAARC_USER / SAARC_DSN в .env (нужны для live-режима).")

        table = settings.SAARC_DOWNTIME_TABLE
        sql = (
            "SELECT НАЧАЛО, КОНЕЦ, ДЛИТЕЛЬНОСТЬ, ПРИЧИНА, ПРИМЕЧАНИЕ, АГГРЕГАТ, УЧАСТОК, ФИО, СЛУЖБА, ЦЕХ "
            f"FROM {table} WHERE 1=1"
        )
        params = {}
        if since:
            sql += " AND НАЧАЛО >= :since"
            params["since"] = since
        if until:
            sql += " AND НАЧАЛО < :until"
            params["until"] = until

        columns = ["НАЧАЛО", "КОНЕЦ", "ДЛИТЕЛЬНОСТЬ", "ПРИЧИНА", "ПРИМЕЧАНИЕ", "АГГРЕГАТ", "УЧАСТОК", "ФИО", "СЛУЖБА", "ЦЕХ"]
        try:
            with oracledb.connect(
                user=settings.SAARC_USER,
                password=settings.SAARC_PASSWORD,
                dsn=settings.SAARC_DSN,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql, params)
                    return [SourceRow(dict(zip(columns, raw))) for raw in cursor.fetchall()]
        except Exception as exc:  # noqa: BLE001 — показываем понятную ошибку наверх
            raise SaarcSourceError(f"Не удалось прочитать данные из СААРЦ: {exc}") from exc


def _in_period(text, since, until) -> bool:
    """Проверяет, попадает ли строка с датой-текстом в период (для мок-режима)."""
    try:
        moment = datetime.strptime(str(text)[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return True
    if since and moment < since:
        return False
    if until and moment >= until:
        return False
    return True
