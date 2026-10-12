"""Read-only personal assessment behind existing full-admin and case gates."""
import logging

from fastapi import Depends, HTTPException, Path, Request
from fastapi.responses import HTMLResponse

import app.admin.router as ar
from app.admin import kg_entry as entry
from app.admin.assessment_copy import reasons
from app.domain import connected_qualification as service
from app.domain.assessment_policy import configured_policy as assessment_policy
from app.domain.entry_interview_policy import policy_from_document
from app.domain.entry_storage import EntryStorageInvalid
from app.domain.knowledge_publication_rules import configured_policy as publication_policy
from app.domain.qualification_policy import configured_policy as qualification_policy
from app.domain.service_authz import PermissionDenied

log = logging.getLogger(__name__)
HEADERS = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}


@ar.router.get('/case/{case_id}/kg-entry/applicants/{applicant_id}/assessment', response_class=HTMLResponse)
async def assessment(request: Request, case_id: int = Path(ge=1, le=2147483647),
                     applicant_id: int = Path(ge=1, le=2147483647), manager=Depends(ar.require_full_admin)):
    actor = entry._gate(request, manager)
    if request.query_params:
        raise HTTPException(422)
    report = None; status = 200
    try:
        ip = policy_from_document(ar.settings.kg_interview_policy) if ar.settings.kg_interview_policy else None
        report = await service.assess(entry._engine(), actor=actor, case_id=case_id, applicant_id=applicant_id,
            assessment_policy=assessment_policy(ar.settings), qualification_policy=qualification_policy(ar.settings),
            publication_policy=publication_policy(ar.settings), interview_policy=ip)
    except PermissionDenied:
        raise HTTPException(403) from None
    except EntryStorageInvalid as exc:
        if str(exc) in ('applicant_unavailable', 'application_case_unavailable'):
            raise HTTPException(404) from None
        status = 503
    except Exception:
        status = 503
    if status == 503:
        log.warning('Current personal assessment unavailable')
    return ar.templates.TemplateResponse(request, 'kg_assessment.html',
        dict(manager=manager, report=report, reason_labels=reasons(report) if report else [],
             case_id=case_id, applicant_id=applicant_id), status_code=status, headers=HEADERS)
