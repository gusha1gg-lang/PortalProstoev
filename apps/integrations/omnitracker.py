"""
Адаптер ITIL-тикетов OMNITRACKER.

Тикеты связываются с нашими инцидентами (кейсами) и простоями. В разработке работает
мок-версия, на проде — реальный API (модуль requests подключается лениво).

Выбор реализации — в factory.py по флагу INTEGRATION_MODE из .env.
"""
import json
from dataclasses import dataclass, field

from django.conf import settings


class OmniTrackerError(RuntimeError):
    """Понятная ошибка при проблемах с OMNITRACKER."""


@dataclass
class Ticket:
    """Тикет OMNITRACKER в упрощённом виде."""

    external_id: str
    title: str = ""
    status: str = ""
    url: str = ""
    raw: dict = field(default_factory=dict)


class BaseOmniTracker:
    """Общий интерфейс системы тикетов."""

    def fetch_tickets(self, external_ids=None) -> list[Ticket]:
        """Возвращает тикеты (при передаче external_ids — только эти)."""
        raise NotImplementedError

    def create_ticket(self, title, description="", group="", due_at=None) -> Ticket:
        """Создаёт тикет. По умолчанию не поддерживается — реализуют наследники."""
        raise NotImplementedError


# --- Мок-тикеты (для разработки без OMNITRACKER) ---
MOCK_TICKETS = [
    Ticket(
        external_id="INC-100500",
        title="Не работает система ДМАП",
        status="В работе",
        url="https://omniltracker.example/INC-100500",
    ),
    Ticket(
        external_id="INC-100501",
        title="Отказ сервера приложений",
        status="Закрыт",
        url="https://omniltracker.example/INC-100501",
    ),
]


class MockOmniTracker(BaseOmniTracker):
    """Заглушка: отдаёт встроенные тикеты. Работает без OMNITRACKER."""

    # Сквозной счётчик созданных «тикетов», чтобы номера не повторялись.
    _created = 0

    def fetch_tickets(self, external_ids=None) -> list[Ticket]:
        if external_ids:
            wanted = set(external_ids)
            return [t for t in MOCK_TICKETS if t.external_id in wanted]
        return list(MOCK_TICKETS)

    def create_ticket(self, title, description="", group="", due_at=None) -> Ticket:
        """Имитирует создание тикета: выдаёт номер вида INC-900001."""
        MockOmniTracker._created += 1
        external_id = f"INC-{900000 + MockOmniTracker._created}"
        return Ticket(
            external_id=external_id,
            title=title,
            status="Новый",
            url=f"https://omniltracker.example/{external_id}",
            raw={
                "internalId": external_id,
                "subject": title,
                "description": description,
                "group": group,
                "dueAt": due_at.isoformat() if due_at else "",
                "mock": True,
            },
        )


class LiveOmniTracker(BaseOmniTracker):
    """Реальный OMNITRACKER через HTTP API. requests подключается лениво."""

    def fetch_tickets(self, external_ids=None) -> list[Ticket]:
        try:
            import requests  # noqa: F401
        except ImportError as exc:
            raise OmniTrackerError(
                "Не установлен модуль requests (нужен только для live-режима). "
                "Установите: pip install requests"
            ) from exc

        if not settings.OMNITRACKER_BASE_URL:
            raise OmniTrackerError("Не задан OMNITRACKER_BASE_URL в .env (нужен для live-режима).")

        url = settings.OMNITRACKER_BASE_URL.rstrip("/") + "/api/tickets"
        params = {"internalId": ",".join(external_ids)} if external_ids else None
        try:
            response = requests.get(
                url,
                params=params,
                auth=(settings.OMNITRACKER_USER, settings.OMNITRACKER_PASSWORD),
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 — показываем понятную ошибку наверх
            raise OmniTrackerError(f"Не удалось получить тикеты из OMNITRACKER: {exc}") from exc

        tickets = []
        for item in payload if isinstance(payload, list) else payload.get("items", []):
            tickets.append(
                Ticket(
                    external_id=str(item.get("internalId") or item.get("id") or ""),
                    title=item.get("subject") or item.get("title") or "",
                    status=item.get("status") or "",
                    url=item.get("url") or "",
                    raw=item,
                )
            )
        return tickets

    def create_ticket(self, title, description="", group="", due_at=None) -> Ticket:
        """Создаёт тикет в OMNITRACKER через HTTP API."""
        try:
            import requests  # noqa: F401
        except ImportError as exc:
            raise OmniTrackerError(
                "Не установлен модуль requests (нужен только для live-режима). "
                "Установите: pip install requests"
            ) from exc

        if not settings.OMNITRACKER_BASE_URL:
            raise OmniTrackerError("Не задан OMNITRACKER_BASE_URL в .env (нужен для live-режима).")

        url = settings.OMNITRACKER_BASE_URL.rstrip("/") + "/api/tickets"
        body = {
            "subject": title,
            "description": description,
            "group": group,
        }
        if due_at:
            body["dueAt"] = due_at.isoformat()
        try:
            response = requests.post(
                url,
                json=body,
                auth=(settings.OMNITRACKER_USER, settings.OMNITRACKER_PASSWORD),
                timeout=15,
            )
            response.raise_for_status()
            item = response.json()
        except Exception as exc:  # noqa: BLE001 — показываем понятную ошибку наверх
            raise OmniTrackerError(
                f"Не удалось создать тикет в OMNITRACKER: {exc}"
            ) from exc

        return Ticket(
            external_id=str(item.get("internalId") or item.get("id") or ""),
            title=item.get("subject") or title,
            status=item.get("status") or "Новый",
            url=item.get("url") or "",
            raw=item,
        )


def tickets_to_json(tickets) -> str:
    """Помощник для отладки: печатает список тикетов как JSON."""
    return json.dumps([t.__dict__ for t in tickets], ensure_ascii=False, indent=2, default=str)
