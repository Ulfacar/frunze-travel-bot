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


def _render(request: Request, manager: dict, *, phone: str = "", found=None, error: str = "",
            folder: Path | None = None, status_code: int = 200):
    from app.admin.contracts import _csrf
    return ar.templates.TemplateResponse(request, "bitrix_archive.html", {
        "manager": manager, "phone": phone, "found": found, "error": error,
        "csrf_token": _csrf(request),
        "files": {f: (folder / f).is_file() for f in FILES} if folder else {},
    }, status_code=status_code, headers={"Cache-Control": "no-store"})


async def _guard() -> None:
    if settings.crm_standalone_enabled or not await ar._media_flag(FLAG):
        raise HTTPException(status_code=404)


@ar.router.get("/bitrix-archive", response_class=HTMLResponse)
async def bitrix_archive_page(request: Request, manager: dict = Depends(ar.require_full_admin)):
    """Только форма. Номер в адресе не принимается: строка запроса уходит в журналы
    uvicorn/nginx и в историю браузера, а там нужен не весь номер (ревью ux 30.10, A1)."""
    await _guard()
    folder = _archive_dir()
    error = "" if folder else _NO_ARCHIVE
    return _render(request, manager, error=error, folder=folder)


_NO_ARCHIVE = ("Архив не найден. Выгрузите его скриптом bitrix_archive_export.py и укажите "
               "каталог в настройке BITRIX_ARCHIVE_DIR.")


@ar.router.post("/bitrix-archive", response_class=HTMLResponse)
async def bitrix_archive_search(request: Request, manager: dict = Depends(ar.require_full_admin)):
    """Поиск по номеру — POST с токеном формы, как остальные формы панели."""
    import hmac
    await _guard()
    form = await request.form()
    token = str(form.get("csrf_token", ""))
    expected = request.session.get("contract_csrf", "")
    if not expected or not token or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Форма устарела. Откройте её заново.")
    phone = str(form.get("phone", "") or "").strip()[:40]
    found, error = None, ""
    folder = _archive_dir()
    if folder is None:
        error = _NO_ARCHIVE
    elif phone:
        try:
            found = archive.search(folder, phone, with_comments=True)
        except ValueError:
            error = (f"Введите номер полностью: не меньше {archive.MIN_DIGITS} цифр, "
                     "например 0555 123 456 или +7 701 123 45 67.")
        except OSError:
            log.warning("bitrix archive: read failed", exc_info=True)
            error = "Архив не читается — проверьте файлы на сервере."
    if phone:   # кто и что искал в персональных данных; в журнал — только хвост номера
        await ar.get_conversation_store().add_audit(
            manager["login"], "bitrix_archive", "", f"…{archive._digits(phone)[-4:]}")
    return _render(request, manager, phone=phone, found=found, error=error, folder=folder)
