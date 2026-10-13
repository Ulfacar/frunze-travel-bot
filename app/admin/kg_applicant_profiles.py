"""Native individual interview using the existing typed controls and pilot gates."""
import hashlib
import hmac
import logging
import secrets

from fastapi import Depends, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

import app.admin.router as ar
from app.admin import kg_entry as interview
from app.admin.kg_entry_form import FIELDS, FAMILY_LIMIT, FormInvalid, country_options, report_view, request_from_values, values_from_request
from app.admin.workday import _write_on
from app.domain.applicant_profiles import read_applicant_profile, save_applicant_profile
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable
from app.domain.models import DomainError, KnowledgeImport, KnowledgeSet, KnowledgeVersion
from app.domain.service_authz import PermissionDenied

log = logging.getLogger("admin.kg_applicant_profiles")
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _url(case_id, applicant_id):
    return f"/admin/case/{case_id}/kg-entry/applicants/{applicant_id}/qualification"


def _signature(request, actor, case_id, applicant_id, values):
    signed = interview._signature(request, actor, case_id, values)
    return hmac.new(ar.settings.session_secret.encode(),
        f"kg-individual-profile/1:{applicant_id}:{signed}".encode(), hashlib.sha256).hexdigest()


async def _render(request, manager, actor, case, applicant_id, *, qualification_id=None, echo=None, error="", status=200):
    context = {}
    try:
        data = await read_applicant_profile(interview._engine(), actor=actor, case_id=case["id"],
                                            applicant_id=applicant_id, qualification_id=qualification_id)
        saved = data["saved"]
        async with ar._domain_sessionmaker()() as session:
            version_id = saved["provenance"]["context"]["knowledge_version_id"] if saved else None
            if version_id is None:
                accepted = select(KnowledgeImport.id).where(KnowledgeImport.version_id == KnowledgeVersion.id,
                                                            KnowledgeImport.result == "accepted").exists()
                version_id = await session.scalar(select(KnowledgeVersion.id).join(KnowledgeSet,
                    KnowledgeVersion.set_id == KnowledgeSet.id).where(KnowledgeSet.code == "kg_entry",
                    KnowledgeSet.jurisdiction == "KG", KnowledgeSet.domain == "entry", accepted)
                    .order_by(KnowledgeVersion.version.desc()).limit(1))
            version = await session.get(KnowledgeVersion, version_id) if version_id else None
        base = saved["input"] if saved else {}
        envelope = interview._envelope(request, actor, case, saved, version_id, None) if version else None
        if envelope:
            envelope["_kg_signature"] = _signature(request, actor, case["id"], applicant_id, envelope)
        context = dict(applicant=data["applicant"], saved=saved, profile_history=data["history"],
            values=values_from_request(base), countries=country_options(version.country_aliases) if version else [],
            version_label=f"Версия базы №{version.version} · требует проверки" if version else "",
            empty_knowledge=version is None, has_conditions="condition_facts" in base,
            report=report_view(saved["result"]) if saved else None, envelope=envelope,
            editable=saved is None or saved["revision"] == data["current_revision"])
    except PermissionDenied:
        raise HTTPException(403) from None
    except EntryStorageInvalid as exc:
        if str(exc) in ("applicant_unavailable", "application_case_unavailable", "profile_unavailable"):
            raise HTTPException(404) from None
        status = 503
    except Exception:
        status = 503
    if status == 503 and not context:
        log.warning("KG individual interview unavailable")
        codes = set((echo or {}).get("citizenship", [])) | {(echo or {}).get("entry_passport_country", "")}
        codes -= {"", "unknown", "not_applicable"}
        context = dict(applicant=dict(id=applicant_id, ordinal="?"), values=values_from_request({}),
            countries=[(c, c) for c in sorted(codes)], editable=echo is not None)
        error = error or "Анкета или источник временно недоступны. Попробуйте позже."
    if echo is not None:
        context.update(values=echo, envelope={k: echo.get(k, "") for k in (*interview.META, *interview.SECURITY)},
                       editable=True, has_conditions=True)
    return ar.templates.TemplateResponse(request, "kg_entry.html", {**context, "manager": manager, "case": case,
        "individual_profile": True, "fields": FIELDS, "family_limit": FAMILY_LIMIT, "error": error,
        "write_on": _write_on(request), "form_url": _url(case["id"], applicant_id)}, status_code=status, headers=HEADERS)


@ar.router.get("/case/{case_id}/kg-entry/applicants/{applicant_id}/qualification", response_class=HTMLResponse)
async def profile_form(request: Request, case_id: int = Path(ge=1, le=2147483647),
                       applicant_id: int = Path(ge=1, le=2147483647),
                       qualification_id: int | None = Query(None, ge=1, le=2147483647),
                       manager: dict = Depends(ar.require_full_admin)):
    actor = interview._gate(request, manager)
    query = list(request.query_params.multi_items())
    if len(query) > 1 or any(key != "qualification_id" for key, _ in query):
        raise HTTPException(422)
    try:
        case = await interview._case(case_id, actor)
    except HTTPException:
        raise
    except Exception:
        return HTMLResponse("Реестр услуг временно недоступен.", status_code=503, headers=HEADERS)
    return await _render(request, manager, actor, case, applicant_id, qualification_id=qualification_id)


@ar.router.post("/case/{case_id}/kg-entry/applicants/{applicant_id}/qualification", response_class=HTMLResponse)
async def profile_submit(request: Request, case_id: int = Path(ge=1, le=2147483647),
                         applicant_id: int = Path(ge=1, le=2147483647),
                         manager: dict = Depends(ar.require_full_admin)):
    actor = interview._gate(request, manager, write=True)
    try:
        case = await interview._case(case_id, actor)
    except HTTPException:
        raise
    except Exception:
        return HTMLResponse("Реестр услуг временно недоступен. Сохранение не выполнено.", status_code=503, headers=HEADERS)
    values = await interview._form(request)
    signature = values.get("_kg_signature", "")
    if not secrets.compare_digest(signature.encode(), _signature(request, actor, case_id, applicant_id, values).encode()):
        raise HTTPException(403)
    # Reuse CSRF, payer and envelope validation only after the individual signature.
    checked = {**values, "_kg_signature": interview._signature(request, actor, case_id, values)}
    interview._verify(request, actor, case, checked)
    if values.get("_kg_history") != "0":
        raise HTTPException(403)
    try:
        base_id = int(values["_kg_base"])
        data = await read_applicant_profile(interview._engine(), actor=actor, case_id=case_id,
                                            applicant_id=applicant_id, qualification_id=base_id or None)
        base = data["saved"] if base_id else None
        if (base["revision"] if base else 0) != int(values["_kg_revision"]):
            raise EntryStorageConflict("profile_revision_changed")
        submitted = request_from_values(values, as_of=values["_kg_asof"], base_request=base["input"] if base else {})
        saved = await save_applicant_profile(interview._engine(), actor=actor, case_id=case_id, applicant_id=applicant_id,
            expected_revision=int(values["_kg_revision"]), request_key=values["_kg_key"],
            knowledge_version_id=int(values["_kg_version"]), request=submitted)
    except PermissionDenied:
        raise HTTPException(403) from None
    except EntryStorageConflict:
        error, status = "Анкета изменилась в другой вкладке. Сверьте ответы с последней версией.", 409
    except FormInvalid as exc:
        error, status = str(exc), 422
    except EntryStorageUnavailable:
        error, status = "Сохранение не подтверждено. Повторите отправку этой формы без изменений.", 503
    except DomainError:
        error, status = "Проверьте ответы и источник анкеты. Сохранение не выполнено.", 422
    except Exception:
        log.warning("KG individual interview save unavailable")
        error, status = "Сохранение не подтверждено. Повторите отправку этой формы без изменений.", 503
    else:
        return RedirectResponse(_url(case_id, applicant_id) + f"?qualification_id={saved['qualification_id']}",
                                status_code=303, headers=HEADERS)
    return await _render(request, manager, actor, case, applicant_id, echo=values, error=error, status=status)
