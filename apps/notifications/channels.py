"""
Каналы отправки уведомлений.

Канал — это способ доставить сообщение. Сейчас реализован только email.
Добавить новый канал (например, Telegram) = создать класс-наследник BaseChannel
и зарегистрировать его в CHANNELS — правила и логика отправки не меняются.

В разработке email не уходит наружу: Django печатает письмо в консоль
(backend `console`, см. config/settings). На проде backend = SMTP, реквизиты из `.env`.
"""
from dataclasses import dataclass, field

from django.conf import settings
from django.core.mail import send_mail


@dataclass
class Message:
    """Готовое к отправке сообщение."""

    subject: str
    body: str
    recipients: list[str] = field(default_factory=list)


class BaseChannel:
    """Общий «портрет» канала отправки."""

    code = ""

    def send(self, message: Message) -> tuple[str, str]:
        """Отправляет сообщение. Возвращает (итог: sent/failed, текст ошибки)."""
        raise NotImplementedError


class EmailChannel(BaseChannel):
    """Отправка по электронной почте через стандартный механизм Django."""

    code = "email"

    def send(self, message: Message) -> tuple[str, str]:
        if not message.recipients:
            return "failed", "не указаны получатели"
        try:
            sent = send_mail(
                subject=message.subject,
                message=message.body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=message.recipients,
                fail_silently=False,
            )
        except Exception as exc:  # noqa: BLE001 — показываем причину в журнале
            return "failed", str(exc)
        if not sent:
            return "failed", "почтовый сервер не принял письмо"
        return "sent", ""


CHANNELS: dict[str, BaseChannel] = {
    EmailChannel.code: EmailChannel(),
}


def get_channel(code: str) -> BaseChannel:
    """Возвращает канал по коду. Пока поддерживается только email."""
    try:
        return CHANNELS[code]
    except KeyError as exc:
        raise ValueError(f"Неизвестный канал уведомлений: {code}") from exc
