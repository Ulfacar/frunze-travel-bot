# -*- coding: utf-8 -*-
"""Секреты не должны попадать в лог — ни текстом ошибки, ни трейсбеком.

Повод: токен вебхука Битрикса стоит прямо в URL, а `resp.raise_for_status()` кладёт
URL целиком в текст исключения. Любая ошибка портала печатала рабочий ключ в лог, и
перевыпуск ключа бессмыслен, пока это так. То же у TourVisor: логин и пароль уходят
параметрами `authlogin`/`authpass`.

Гейт написан ДО правки и исполнителем НЕ редактируется.
"""
import logging

import httpx
import pytest

from app.config import settings
from app.core import redact as R

TOKEN = "1x2y3z4qwertyuiop"
HOOK = f"https://getvisakg.bitrix24.kz/rest/155383/{TOKEN}"


@pytest.fixture
def secrets(monkeypatch):
    monkeypatch.setattr(settings, "bitrix24_webhook_url", HOOK, raising=False)
    monkeypatch.setattr(settings, "tourvisor_pass", "tvsecret123", raising=False)
    monkeypatch.setattr(settings, "wappi_token", "", raising=False)


def test_bitrix_token_is_masked(secrets):
    text = f"Client error '401' for url '{HOOK}/crm.lead.add.json'"
    out = R.redact(text)
    assert TOKEN not in out
    assert "crm.lead.add.json" in out      # что упало — видно, чем — нет


def test_tourvisor_password_is_masked(secrets):
    out = R.redact("GET .../search.php?authlogin=a@b.c&authpass=tvsecret123&format=json")
    assert "tvsecret123" not in out
    assert "authpass" in out


def test_traceback_of_a_real_http_error_is_masked(secrets):
    """Не текст, который мы сами составили, а настоящее исключение httpx."""
    request = httpx.Request("POST", f"{HOOK}/crm.lead.add.json")
    response = httpx.Response(401, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        record = logging.LogRecord("crm.bitrix24", logging.ERROR, __file__, 1,
                                   "портал ответил ошибкой", (), __import__("sys").exc_info())
    rendered = R.RedactingFormatter("%(message)s").format(record)
    assert TOKEN not in rendered
    assert "401" in rendered


def test_empty_secret_does_not_eat_everything(monkeypatch):
    """Ложное срабатывание: пустые настройки не должны затирать весь текст."""
    monkeypatch.setattr(settings, "bitrix24_webhook_url", "", raising=False)
    monkeypatch.setattr(settings, "tourvisor_pass", "", raising=False)
    monkeypatch.setattr(settings, "wappi_token", "", raising=False)
    assert R.redact("обычная строка без секретов") == "обычная строка без секретов"


def test_short_values_are_not_treated_as_secrets(monkeypatch):
    """«1» или «kg» в настройке не должны вырезать все единицы из логов."""
    monkeypatch.setattr(settings, "tourvisor_pass", "kg", raising=False)
    monkeypatch.setattr(settings, "bitrix24_webhook_url", "", raising=False)
    assert R.redact("Бишкек kg 2 ночи") == "Бишкек kg 2 ночи"


def test_clean_text_passes_through(secrets):
    assert R.redact("лид 181727 переведён в CONVERTED") == "лид 181727 переведён в CONVERTED"


def test_root_log_handlers_actually_use_the_redacting_formatter():
    """Модуль может быть правильным и при этом никуда не подключённым."""
    from app.core.observ import install_request_id_logging

    root = logging.getLogger()
    added = None
    if not root.handlers:
        added = logging.StreamHandler()
        root.addHandler(added)
    try:
        install_request_id_logging()
        assert root.handlers
        assert all(isinstance(h.formatter, R.RedactingFormatter) for h in root.handlers)
    finally:
        if added is not None:
            root.removeHandler(added)
