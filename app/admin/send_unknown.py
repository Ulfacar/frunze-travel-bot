"""Статус «неизвестно» у ручного сообщения менеджера (ТЗ MSG-02, флаг OFF).

Зачем. С пилота менеджеры отвечают только из панели. Если Wappi принял запрос, а ответ
не дошёл до нас (таймаут чтения, обрыв соединения, 5xx шлюза), сообщение МОГЛО уйти
клиенту. Сейчас такое сообщение получает «не доставлено» и кнопку «Повторить» — повтор
отправляет клиенту второе такое же сообщение (ревью pm/ux 30.10, тест
`test_timeout_then_retry_sends_twice`).

Правило то же, что уже действует для файлов (`send_file` в `router.py`, ревью B2a):

* **не доставлено** (`failed`) — запрос до Wappi точно не дошёл или Wappi явно отказал:
  нет соединения (`ConnectError`, `ConnectTimeout`, `PoolTimeout`), ответ 4xx (402 «не
  оплачено», 401, 400), канал не настроен, нет адаптера;
* **неизвестно** (`unknown`) — запрос мог быть принят: таймаут чтения/записи, обрыв
  соединения после отправки, ответ 5xx, `SendOutcomeUnknown`, отменённый запрос.

Повтор `unknown` сервер выполняет только с явным подтверждением (`confirm=1` в форме):
менеджер видит «Клиент может получить сообщение дважды». Подтверждение относится к тому
`unknown`, которое менеджер видел: кнопка несёт отметку попытки (`seen`), каждая
завершённая попытка повтора её меняет. Две вкладки или два клика, оба по одному `unknown`,
после нового таймаута первого не дают третьей копии — второму нужно подтвердить заново
(ревью pdf 30.10, проба P1c). Флаг
`panel_send_unknown_status_enabled`, дефолт OFF: без него всё как было — `failed`.
"""
from __future__ import annotations

import asyncio
import secrets

import httpx

FLAG = "panel_send_unknown_status_enabled"
CONFIRM_FIELD = "confirm"
SEEN_FIELD = "seen"

# Отметка попытки: «запуск процесса.номер завершённой попытки». Живёт в памяти процесса,
# как и блокировки повтора в `router.resend` (один воркер uvicorn). После перезапуска
# меняется первая часть — любая страница, открытая до него, требует нового подтверждения.
_BOOT = secrets.token_hex(4)
_attempts: dict[int, int] = {}

# Запрос до провайдера не ушёл — повтор безопасен.
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout,
             httpx.UnsupportedProtocol, httpx.InvalidURL)


def classify(exc: BaseException) -> str:
    """`failed` — точно не ушло; `unknown` — могло уйти."""
    if isinstance(exc, _NOT_SENT):
        return "failed"
    if isinstance(exc, httpx.HTTPStatusError):
        return "unknown" if exc.response.status_code >= 500 else "failed"
    if isinstance(exc, (httpx.TransportError, asyncio.CancelledError)):
        return "unknown"
    from app.channels.wappi import SendOutcomeUnknown
    if isinstance(exc, SendOutcomeUnknown):
        return "unknown"
    return "failed"            # канал не настроен, нет адаптера, ошибка до сети


def seen_token(message_id: int) -> str:
    """Отметка для кнопки «Отправить ещё раз»: какое именно `unknown` видел менеджер."""
    return f"{_BOOT}.{_attempts.get(message_id, 0)}"


def attempt_finished(message_id: int) -> None:
    """Попытка повтора завершилась (любым исходом) — прежние подтверждения устарели."""
    _attempts[message_id] = _attempts.get(message_id, 0) + 1


async def enabled() -> bool:
    from app.admin import router as ar
    return await ar._media_flag(FLAG)


async def failure_status(exc: BaseException) -> str:
    """Статус сообщения после исключения отправки. Флаг OFF — всегда `failed`."""
    try:
        if not await enabled():
            return "failed"
    except Exception:  # noqa: BLE001 — флаг недоступен: прежнее поведение
        return "failed"
    return classify(exc)


async def retryable(status: str, *, confirmed: bool) -> bool:
    """Можно ли повторить сообщение с этим статусом."""
    if status == "failed":
        return True
    return status == "unknown" and confirmed and await enabled()
