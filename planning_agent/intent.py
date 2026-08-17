from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from pydantic import BaseModel, ValidationError

from .llm import _json_object
from .local_llm import LocalLLM


class IntentSchema(BaseModel):
    general: bool
    rag: bool
    planning: bool


@dataclass(frozen=True)
class IntentDecision:
    general: bool = False
    rag: bool = False
    planning: bool = False
    method: str = "local-llm"

    def to_dict(self) -> dict[str, bool | str]:
        return asdict(self)


def route_request(client: LocalLLM, request: str) -> IntentDecision:
    """Classify a request into non-exclusive paths using only the local model."""
    raw = client.chat([
        {"role": "system", "content": (
            "Classify the request for a private industrial assistant. Return JSON only with boolean "
            "keys general, rag, planning. Multiple values may be true. planning is true when the user "
            "asks to create, optimize, change, or evaluate a resource schedule. rag is true when the "
            "request needs company files, SOPs, policies, workbooks, resource facts, or cited evidence. "
            "general is true only for ordinary conversation or general knowledge that does not require "
            "company files or scheduling. Never make rag or planning false merely because another is true."
        )},
        {"role": "user", "content": request},
    ], temperature=0.0)
    try:
        parsed = IntentSchema.model_validate(json.loads(_json_object(raw)))
    except (json.JSONDecodeError, ValidationError):
        return _fallback_route(request)
    if not (parsed.general or parsed.rag or parsed.planning):
        return IntentDecision(general=True)
    return IntentDecision(parsed.general, parsed.rag, parsed.planning)


def _fallback_route(request: str) -> IntentDecision:
    """Conservative local fallback when model JSON is malformed."""
    text = request.casefold()
    planning_terms = ("schedule", "reschedule", "plan jobs", "allocate", "optimizer", "or-tools", "makespan")
    rag_terms = ("sop", "policy", "document", "file", "workbook", "company", "ppe", "safety", "worker", "machine")
    planning = any(term in text for term in planning_terms)
    rag = any(term in text for term in rag_terms)
    return IntentDecision(general=not (rag or planning), rag=rag, planning=planning, method="rule-fallback")
