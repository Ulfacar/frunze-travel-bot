"""Страница «Архив Битрикса»: найти старого клиента по телефону после отключения портала.

Читает JSONL, который пишет `scripts/bitrix_archive_export.py`, из каталога
`settings.bitrix_archive_dir` на сервере. Только чтение: ни портал, ни база панели не
трогаются. Поиск потоковый (`app/integrations/crm/bitrix_archive.search`): архив любого
размера целиком в память не грузится.

**Права — только полный администратор.** Направление клиента (визы или туры) из
архива надёжно не выводится: у лида нет воронки, у сделки воронка — `CATEGORY_ID`,
соответствие категорий направлениям на реальном портале не сверено, а ответственный
(`ASSIGNED_BY_ID`) — признак человека, а не команды (лиды бота висели на служебном
аккаунте). Открыть менеджерам можно после сверки на настоящем архиве — см. отчёт
`docs/pm-review-2026-10-30/bitrix.md`. Флаг `panel_bitrix_archive_enabled`, дефолт OFF.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.admin import router as ar
from app.config import settings
from app.integrations.crm import bitrix_archive as archive

log = logging.getLogger("admin.bitrix_archive")
FLAG = "panel_bitrix_archive_enabled"
FILES = ("contacts.jsonl", "leads.jsonl", "deals.jsonl", "timeline.jsonl")


def _archive_dir() -> Path | None:
    raw = (settings.bitrix_archive_dir or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_dir() or not any((path / f).is_file() for f in FILES[:3]):
        return None
    return path


@ar.router.get("/bitrix-archive", response_class=HTMLResponse)
async def bitrix_archive_page(request: Request, phone: str = "",
                              manager: dict = Depends(ar.require_full_admin)):
    if settings.crm_standalone_enabled or not await ar._media_flag(FLAG):
        raise HTTPException(status_code=404)
    phone = (phone or "").strip()[:40]
    found, error = None, ""
    folder = _archive_dir()
    if folder is None:
        error = ("Архив не найден. Выгрузите его скриптом bitrix_archive_export.py и укажите "
                 "каталог в настройке BITRIX_ARCHIVE_DIR.")
    elif phone:
        try:
            found = archive.search(folder, phone, with_comments=True)
        except ValueError:
            error = f"Введите номер: не меньше {archive.MIN_DIGITS} цифр."
        except OSError:
            log.warning("bitrix archive: read failed", exc_info=True)
            error = "Архив не читается — проверьте файлы на сервере."
    if phone:   # кто и что искал в персональных данных; в журнал — только хвост номера
        await ar.get_conversation_store().add_audit(
            manager["login"], "bitrix_archive", "", f"…{archive._digits(phone)[-4:]}")
    return ar.templates.TemplateResponse(request, "bitrix_archive.html", {
        "manager": manager, "phone": phone, "found": found, "error": error,
        "files": {f: (folder / f).is_file() for f in FILES} if folder else {},
    }, headers={"Cache-Control": "no-store"})
