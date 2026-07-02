"""Model routing for LLM calls."""
from __future__ import annotations

from app.config import settings


TOURS_ESCALATION_TERMS = (
    "брон",
    "оплат",
    "цена",
    "стоимост",
    "дорог",
    "скидк",
)


def choose_model(scenario: str, escalated: bool) -> str:
    """Return the configured model for a funnel and escalation state."""
    if scenario in {"visa", "tickets"}:
        return settings.llm_model_cheap
    if scenario == "tours" and escalated:
        return settings.llm_model_main
    return settings.llm_model_cheap


def should_escalate_tours_input(text: str) -> bool:
    """Cheap pre-check for money/booking objections before a tours LLM turn."""
    lowered = (text or "").lower()
    return any(term in lowered for term in TOURS_ESCALATION_TERMS)
