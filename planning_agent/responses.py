from __future__ import annotations

from typing import Any

from .intent import IntentDecision
from .models import ScheduleResult
from .rag import Passage


def compose_response(
    answer: str,
    intents: IntentDecision,
    passages: list[Passage],
    timing: dict[str, float],
    schedule: ScheduleResult | None = None,
    schedule_id: str | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []
    schedule_payload: dict[str, Any] | None = None
    if intents.rag and not passages:
        warnings.append("No relevant approved workspace evidence was found.")
    if schedule is not None:
        warnings.extend(f"{item.task}: {item.reason}" for item in schedule.unscheduled)
        missed = [item.task for item in schedule.scheduled if item.deadline_met is False]
        if missed:
            warnings.append("Deadline missed: " + ", ".join(missed))
        schedule_payload = {
            "id": schedule_id,
            "tasks": [item.__dict__ for item in schedule.scheduled],
            "unscheduled": [item.__dict__ for item in schedule.unscheduled],
            "solver_status": schedule.solver.get("status", "UNKNOWN"),
            "makespan_hours": schedule.makespan_hours,
            "approval_status": "draft",
        }
    timing["total_seconds"] = round(sum(value for key, value in timing.items() if key != "total_seconds"), 3)
    return {
        "answer": answer,
        "intents": intents.to_dict(),
        "schedule": schedule_payload,
        "sources": [source_payload(passage) for passage in passages],
        "warnings": warnings,
        "timing": timing,
    }


def source_payload(passage: Passage) -> dict[str, Any]:
    return {"document": passage.document, "location": passage.location, "score": round(passage.score, 3)}
