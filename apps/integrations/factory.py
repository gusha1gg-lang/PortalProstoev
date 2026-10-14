"""
Выбор реализации адаптеров: mock или live.

Режим задаётся в .env переменной INTEGRATION_MODE:
    mock — разработка без доступа к корпоративным системам (встроенные данные);
    live — прод в доменной сети (реальные Oracle и OMNITRACKER).

Доменная логика (импорт, расчёты) про этот выбор ничего не знает — она работает
с общим интерфейсом адаптера.
"""
from django.conf import settings

from .omnitracker import BaseOmniTracker, LiveOmniTracker, MockOmniTracker
from .oracle import BaseOracleSource, LiveOracleSource, MockOracleSource


def is_mock() -> bool:
    """True, если интеграции работают в мок-режиме."""
    return getattr(settings, "INTEGRATION_MODE", "mock") != "live"


def get_oracle_source() -> BaseOracleSource:
    """Возвращает источник простоев (Oracle): mock или live."""
    return MockOracleSource() if is_mock() else LiveOracleSource()


def get_omnitracker() -> BaseOmniTracker:
    """Возвращает адаптер тикетов OMNITRACKER: mock или live."""
    return MockOmniTracker() if is_mock() else LiveOmniTracker()
