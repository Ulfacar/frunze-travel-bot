"""Read-only source search for the existing full-admin KG pilot."""
from fastapi import Depends, Request
from fastapi.responses import HTMLResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.knowledge.corpus import RAG_BLOCKS
from app.knowledge.retrieval import RetrievalError, load_review_index


@ar.router.get("/kg-entry/knowledge", response_class=HTMLResponse)
def knowledge_search(request: Request, manager=Depends(ar.require_full_admin)):
    entry._gate(request, manager)
    query = request.query_params.get("q", "")
    block = request.query_params.get("block", "")
    error, report, status = "", None, 200
    try:
        pairs = list(request.query_params.multi_items())
        if (any(key not in {"q", "block"} for key, _ in pairs)
                or len({key for key, _ in pairs}) != len(pairs)
                or block and block not in {str(b) for b in RAG_BLOCKS}
                or len(query) > 200 or any(ord(c) < 32 for c in query)):
            raise RetrievalError("invalid_search_query")
        report = load_review_index().search(query, block=int(block) if block else None)
    except RetrievalError as exc:
        if str(exc) == "invalid_search_query":
            error, status = "Введите запрос до 200 символов и выберите блок из списка.", 422
        else:
            error, status = "Исходная база недоступна или не прошла проверку целостности. Повторите позже.", 503
    return ar.templates.TemplateResponse(request, "kg_knowledge.html", {
        "manager": manager, "query": query[:200], "selected_block": block if block in {str(b) for b in RAG_BLOCKS} else "",
        "blocks": RAG_BLOCKS, "report": report, "error": error,
    }, status_code=status, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
