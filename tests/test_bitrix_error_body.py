# -*- coding: utf-8 -*-
"""Ошибка портала без тела ответа — это не диагноз, а гадание.

Прод 20–22.09.2026: 869 ответов `403 Forbidden` от портала, и все строго ночью
(пик 04:00–07:00, днём ноль). Права были ни при чём — вебхук в это же время отдавал
`profile.json` с `ADMIN: true`. Но что именно сказал портал, узнать было неоткуда:
`resp.raise_for_status()` поднимал исключение, не заглянув в тело, а причину Битрикс
пишет именно там — `QUERY_LIMIT_EXCEEDED`, `OPERATION_TIME_LIMIT` и «нет прав» приходят
под одним и тем же HTTP 403.

Логируем тело, но не URL: в URL живёт токен вебхука.
"""
import asyncio
import logging

import httpx
import pytest

from app.integrations.crm import bitrix24

WEBHOOK = "https://portal/rest/1/s3cr3t-token-value"


class ErrorClient:
    """Портал, отвечающий ошибкой с телом."""

    def __init__(self, status: int, body: dict):
        self.status, self.body = status, body

    async def post(self, url, json):
        return httpx.Response(self.status, json=self.body,
                              request=httpx.Request("POST", url))


@pytest.fixture(autouse=True)
def _webhook(monkeypatch):
    monkeypatch.setattr(bitrix24.settings, "bitrix24_webhook_url", WEBHOOK)
    # `test_alembic_domain_migration` поднимает `alembic/env.py`, а тот зовёт
    # `fileConfig(alembic.ini)` — и тот гасит ВСЕ уже созданные логгеры
    # (`disable_existing_loggers` по умолчанию). В одиночку тест зелёный, в общем прогоне
    # `caplog` не видит ни одной записи. Включаем логгер явно, иначе тест проверяет
    # порядок файлов в каталоге, а не поведение кода.
    logging.getLogger("crm.bitrix24").disabled = False


def _call(client, method="crm.timeline.comment.add"):
    return asyncio.run(bitrix24.Bitrix24Crm(client=client)._call(method, {}))


def test_error_body_reaches_the_log(caplog):
    """Без этого ночной 403 не отличить от отзыва прав."""
    client = ErrorClient(403, {"error": "QUERY_LIMIT_EXCEEDED",
                               "error_description": "Too many requests"})
    with caplog.at_level(logging.WARNING, logger="crm.bitrix24"):
        with pytest.raises(httpx.HTTPStatusError):
            _call(client)
    record = "\n".join(r.getMessage() for r in caplog.records)
    assert "QUERY_LIMIT_EXCEEDED" in record
    assert "403" in record
    assert "crm.timeline.comment.add" in record


def test_webhook_token_is_not_in_the_message(caplog):
    """Сообщение не несёт URL: токен вебхука в лог не попадает даже до `redact`."""
    client = ErrorClient(403, {"error": "ACCESS_DENIED"})
    with caplog.at_level(logging.WARNING, logger="crm.bitrix24"):
        with pytest.raises(httpx.HTTPStatusError):
            _call(client)
    assert "s3cr3t-token-value" not in "\n".join(r.getMessage() for r in caplog.records)


def test_success_is_silent(caplog):
    """Удачный вызов не должен шуметь: иначе предупреждение перестанут читать."""
    class OkClient:
        async def post(self, url, json):
            return httpx.Response(200, json={"result": 1},
                                  request=httpx.Request("POST", url))

    with caplog.at_level(logging.WARNING, logger="crm.bitrix24"):
        assert _call(OkClient()) == {"result": 1}
    assert not [r for r in caplog.records if r.name == "crm.bitrix24"]
