"""Pilot KG interview from an existing visa case, behind an OFF-by-default gate."""
import hashlib
import hmac
import json
import logging
import re
import secrets
from urllib.parse import parse_qsl

from fastapi import Depends, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

import app.admin.router as ar
from app.admin.kg_entry_form import (FIELDS, FORM_FIELDS, FormInvalid, country_options,
                                    report_view, request_from_values, values_from_request)
from app.admin.kg_review_card import card_view
from app.admin.workday import _case_or_404, _require_workday, _write_on
from app.core.live_authz import actor_for
from app.domain.entry_qualification import _qualification_sources
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable, _authorize
from app.domain.models import DomainError, KnowledgeImport, KnowledgeSet, KnowledgeVersion, StayHistory
from app.domain.qualification_storage import read_qualification, save_qualification
from app.domain.qualification_card import read_qualification_card
from app.domain.service_authz import PermissionDenied

log = logging.getLogger("admin.kg_entry")
META = ("_kg_key", "_kg_contact", "_kg_base", "_kg_revision", "_kg_version", "_kg_history", "_kg_asof")
SECURITY = {"_kg_csrf", "_kg_signature"}
BODY_LIMIT = 16_384


def _gate(request, manager, *, write=False):
    _require_workday(request)
    if not ar.settings.admin_kg_entry_enabled:
        raise HTTPException(404)
    actor = actor_for(manager)
    try:
        _authorize(actor)
    except PermissionDenied:
        raise HTTPException(403) from None
    if write and not _write_on(request):
        raise HTTPException(403, "Сохранение анкет отключено администратором.")
    return actor


def _engine():
    return ar._domain_sessionmaker().kw["bind"]


async def _case(case_id, actor):
    async with ar._domain_sessionmaker()() as session:
        case, product = await _case_or_404(session, case_id, actor)
        if product is None or product.direction != "visa":
            raise HTTPException(404)
        return {"id": case.id, "contact_id": case.contact_id, "title": product.name}


def _csrf(request):
    if not request.session.get("kg_entry_csrf"):
        request.session["kg_entry_csrf"] = secrets.token_hex(32)
    return request.session["kg_entry_csrf"]


def _signature(request, actor, case_id, values):
    payload = json.dumps(["kg-entry-form/1", actor.manager_id, case_id, _csrf(request),
                          [values.get(k, "") for k in META]], separators=(",", ":")).encode()
    return hmac.new(ar.settings.session_secret.encode(), payload, hashlib.sha256).hexdigest()


def _envelope(request, actor, case, saved, version_id, history_id):
    values = dict(zip(META, (secrets.token_hex(24), str(case["contact_id"]),
        str(saved["qualification_id"] if saved else 0), str(saved["revision"] if saved else 0),
        str(version_id), str(history_id or 0), ar._bishkek_today().isoformat())))
    values.update(_kg_csrf=_csrf(request), _kg_signature=_signature(request, actor, case["id"], values))
    return values


def _verify(request, actor, case, values):
    token = request.session.get("kg_entry_csrf", "")
    if (not token or not secrets.compare_digest(values.get("_kg_csrf", "").encode(), token.encode())
            or not re.fullmatch(r"[a-f0-9]{48}", values.get("_kg_key", ""))
            or not secrets.compare_digest(values.get("_kg_signature", "").encode(),
                                           _signature(request, actor, case["id"], values).encode())
            or values.get("_kg_contact") != str(case["contact_id"])):
        raise HTTPException(403, "Форма устарела или изменена. Откройте анкету заново.")


async def _form(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Используйте форму анкеты.")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > BODY_LIMIT:
            raise HTTPException(413, "Форма слишком большая.")
        body.extend(chunk)
    try:
        pairs = parse_qsl(body.decode("utf-8", errors="strict"), keep_blank_values=True,
                          max_num_fields=70, encoding="utf-8", errors="strict")
    except (ValueError, UnicodeError):
        raise HTTPException(422, "Не удалось прочитать форму.") from None
    values = {"citizenship": []}
    seen = set()
    for name, value in pairs:
        if name not in FORM_FIELDS | set(META) | SECURITY or len(value) > 128:
            raise HTTPException(422, "Недопустимое поле анкеты.")
        if name in seen and name != "citizenship":
            raise HTTPException(422, "Повторяющееся поле анкеты.")
        seen.add(name)
        if name == "citizenship":
            values[name].append(value)
            if len(values[name]) > 5:
                raise HTTPException(422, "Укажите не более пяти гражданств.")
        else:
            values[name] = value
    return values


async def _context(request, case, actor, qualification_id=None):
    engine = _engine()
    latest = await read_qualification(engine, actor=actor, contact_id=case["contact_id"])
    try:
        saved = (await read_qualification(engine, actor=actor, contact_id=case["contact_id"], qualification_id=qualification_id)
                 if qualification_id is not None else latest)
    except EntryStorageInvalid as exc:
        if str(exc) == "qualification_unavailable":
            raise HTTPException(404) from None
        raise
    history_id = None
    async with ar._domain_sessionmaker()() as session:
        if saved:
            pinned = saved["provenance"]["context"]
            version_id = pinned["knowledge_version_id"]
            history_id = pinned["history"].get("history_id")
        else:
            accepted = select(KnowledgeImport.id).where(KnowledgeImport.version_id == KnowledgeVersion.id,
                                                       KnowledgeImport.result == "accepted").exists()
            version_id = await session.scalar(select(KnowledgeVersion.id).join(KnowledgeSet,
                KnowledgeVersion.set_id == KnowledgeSet.id).where(KnowledgeSet.code == "kg_entry",
                KnowledgeSet.jurisdiction == "KG", KnowledgeSet.domain == "entry", accepted)
                .order_by(KnowledgeVersion.version.desc()).limit(1))
            history_id = await session.scalar(select(StayHistory.id).where(StayHistory.contact_id == case["contact_id"])
                                              .order_by(StayHistory.revision.desc()).limit(1))
        if version_id is None:
            return {"empty_knowledge": True, "saved": None, "values": values_from_request({}), "editable": False}
        await _qualification_sources(session, case["contact_id"], version_id, history_id)
        version = await session.get(KnowledgeVersion, version_id)
        countries = country_options(version.country_aliases)
        version_label = f"Версия базы №{version.version} · требует проверки"
    base = saved["input"] if saved else {}
    return {"saved": saved, "values": values_from_request(base), "countries": countries,
            "version_label": version_label, "has_conditions": "condition_facts" in base,
            "report": report_view(saved["result"]) if saved else None,
            "editable": qualification_id is None or latest is not None and saved["qualification_id"] == latest["qualification_id"],
            "envelope": _envelope(request, actor, case, saved, version_id, history_id)}


async def _render(request, manager, actor, case, *, qualification_id=None, echo=None, error="", status=200):
    try:
        context = await _context(request, case, actor, qualification_id)
    except PermissionDenied:
        raise HTTPException(403) from None
    except HTTPException:
        raise
    except Exception:
        log.warning("KG interview: registry or source unavailable")
        # A verified POST must remain retryable even if a second registry read fails.
        # These are only the caller's own echoed codes, escaped by Jinja; saving still
        # reloads and verifies the real source, never trusting these fallback options.
        codes = set((echo or {}).get("citizenship", [])) | {(echo or {}).get("entry_passport_country", "")}
        codes -= {"", "unknown", "not_applicable"}
        context, status = {"editable": echo is not None, "values": values_from_request({}),
            "countries": [(code, code) for code in sorted(codes)], "has_conditions": echo is not None,
            "version_label": "Источник временно недоступен"}, 503
        error = error or "Анкета или база знаний временно недоступна. Попробуйте ещё раз."
    if echo is not None:
        context["values"] = echo
        context["envelope"] = {k: echo.get(k, "") for k in (*META, *SECURITY)}
    return ar.templates.TemplateResponse(request, "kg_entry.html", {**context, "manager": manager, "case": case,
        "fields": FIELDS, "error": error, "write_on": _write_on(request),
        "form_url": f"/admin/case/{case['id']}/kg-entry"}, status_code=status,
        headers={"Cache-Control": "no-store", "X-Action-Outcome": "failed" if status == 503 else "invalid" if error else "form"})


@ar.router.get("/case/{case_id}/kg-entry", response_class=HTMLResponse)
async def qualification_form(case_id: int, request: Request, qualification_id: int | None = Query(None, ge=1),
                             manager: dict = Depends(ar.require_full_admin)):
    actor = _gate(request, manager)
    try:
        case = await _case(case_id, actor)
    except HTTPException:
        raise
    except Exception:
        return HTMLResponse("Реестр услуг временно недоступен.", status_code=503, headers={"Cache-Control": "no-store"})
    return await _render(request, manager, actor, case, qualification_id=qualification_id)


@ar.router.post("/case/{case_id}/kg-entry", response_class=HTMLResponse)
async def qualification_submit(case_id: int, request: Request, manager: dict = Depends(ar.require_full_admin)):
    actor = _gate(request, manager, write=True)
    try:
        case = await _case(case_id, actor)
    except HTTPException:
        raise
    except Exception:
        return HTMLResponse("Реестр услуг временно недоступен. Сохранение не выполнено.", status_code=503,
                            headers={"Cache-Control": "no-store"})
    values = await _form(request)
    _verify(request, actor, case, values)
    try:
        base_id = int(values["_kg_base"])
        base = await read_qualification(_engine(), actor=actor, contact_id=case["contact_id"], qualification_id=base_id) if base_id else None
        if (base["revision"] if base else 0) != int(values["_kg_revision"]):
            raise FormInvalid("Версия анкеты изменилась. Откройте последнюю анкету.")
        submitted = request_from_values(values, as_of=values["_kg_asof"], base_request=base["input"] if base else {})
        saved = await save_qualification(_engine(), actor=actor, contact_id=case["contact_id"],
            expected_revision=int(values["_kg_revision"]), request_key=values["_kg_key"],
            knowledge_version_id=int(values["_kg_version"]), history_id=int(values["_kg_history"]) or None, request=submitted)
    except PermissionDenied:
        raise HTTPException(403) from None
    except EntryStorageConflict:
        return await _render(request, manager, actor, case, echo=values, status=409,
            error="Анкета уже сохранена или изменена в другой вкладке. Введённые ответы оставлены ниже. Откройте последнюю анкету и сверьте изменения.")
    except FormInvalid as exc:
        return await _render(request, manager, actor, case, echo=values, status=422, error=str(exc))
    except EntryStorageUnavailable:
        return await _render(request, manager, actor, case, echo=values, status=503,
            error="Не удалось подтвердить сохранение. Ответы сохранены в этой форме: повторите отправку без изменений, чтобы проверить результат.")
    except DomainError:
        return await _render(request, manager, actor, case, echo=values, status=422,
            error="Проверьте ответы: гражданство должно соответствовать паспорту, даты — идти по порядку. Если данные верны, нужна проверка источников администратором.")
    except Exception:
        log.warning("KG interview: save unavailable")
        return await _render(request, manager, actor, case, echo=values, status=503,
                             error="Сохранение не подтверждено. Попробуйте повторить отправку этой формы.")
    return RedirectResponse(f"/admin/case/{case_id}/kg-entry?qualification_id={saved['qualification_id']}", status_code=303,
                            headers={"Cache-Control": "no-store", "X-Action-Outcome": "qualification_saved"})


@ar.router.get("/case/{case_id}/kg-entry/review/{qualification_id}", response_class=HTMLResponse)
async def qualification_review_card(request: Request, case_id: int = Path(ge=1, le=2147483647),
                                    qualification_id: int = Path(ge=1, le=2147483647),
                                    manager: dict = Depends(ar.require_full_admin)):
    actor = _gate(request, manager)
    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    try:
        card = await read_qualification_card(_engine(), actor=actor, case_id=case_id,
                                              qualification_id=qualification_id)
        view = card_view(card)
        return ar.templates.TemplateResponse(request, "kg_review_card.html", {
            **card, **view, "manager": manager, "form_url": f"/admin/case/{case_id}/kg-entry",
        }, headers=headers)
    except PermissionDenied:
        raise HTTPException(403) from None
    except EntryStorageInvalid as exc:
        if str(exc) in ("qualification_card_unavailable", "qualification_unavailable"):
            return HTMLResponse("Карточка не найдена.", status_code=404, headers=headers)
    except Exception:
        pass
    log.warning("KG review card: registry, snapshot or source unavailable")
    return HTMLResponse("Карточка проверки временно недоступна. Попробуйте открыть её позже.",
                        status_code=503, headers=headers)
