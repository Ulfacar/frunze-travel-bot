# -*- coding: utf-8 -*-
"""Сбой соединения с порталом — повторяем, а не теряем запись.

Прод 14.09.2026: DNS хостинга 46 раз за день не ответил вовремя (`[Errno -5] No address
associated with hostname`). 7 реплик клиентов и менеджеров не доехали в ленту карточек —
запрос к порталу падал с первой попытки и больше не повторялся.

Повторяем только то, что точно не дошло до портала (ConnectError/ConnectTimeout). Таймаут
чтения не повторяем: портал мог уже принять `crm.lead.add`, и повтор завёл бы дубль.
"""
import asyncio

import httpx
import pytest

from app.integrations.crm import bitrix24


class FlakyClient:
    def __init__(self, failures, exc=httpx.ConnectError):
        self.failures, self.exc, self.calls = failures, exc, 0

    async def post(self, url, json):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc("[Errno -5] No address associated with hostname")
        return httpx.Response(200, json={"result": 42}, request=httpx.Request("POST", url))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def instant(_):
        return None
    monkeypatch.setattr(bitrix24.asyncio, "sleep", instant)
    monkeypatch.setattr(bitrix24.settings, "bitrix24_webhook_url", "https://portal/rest/1/tok")


def _call(client):
    return asyncio.run(bitrix24.Bitrix24Crm(client=client)._call("crm.timeline.comment.add", {}))


def test_one_dns_hiccup_is_survived():
    client = FlakyClient(failures=1)
    assert _call(client) == {"result": 42}
    assert client.calls == 2


def test_connect_timeout_is_retried_too():
    client = FlakyClient(failures=2, exc=httpx.ConnectTimeout)
    assert _call(client) == {"result": 42}
    assert client.calls == 3


def test_gives_up_after_retries():
    client = FlakyClient(failures=10)
    with pytest.raises(httpx.ConnectError):
        _call(client)
    assert client.calls == 3


def test_read_timeout_is_not_retried():
    """Запрос мог дойти — повтор `crm.lead.add` завёл бы вторую карточку."""
    client = FlakyClient(failures=1, exc=httpx.ReadTimeout)
    with pytest.raises(httpx.ReadTimeout):
        _call(client)
    assert client.calls == 1
