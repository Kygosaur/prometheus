from __future__ import annotations

from pathlib import Path

from redis import Redis
from rq import Queue

from .data import load_workbook
from .database import PlanningDatabase
from .llm import understand_request
from .local_llm import LocalLLM
from .scheduler import OptimizationOptions, create_schedule
from .settings import Settings, get_settings


def schedule_job(request_text: str, actor: str, max_solver_seconds: float) -> dict[str, object]:
    settings = get_settings()
    client = LocalLLM(settings.local_llm_base_url, settings.local_llm_model)
    parsed = understand_request(client, request_text)
    workers, tasks, machines, vehicles = load_workbook(Path(settings.planning_workbook))
    result = create_schedule(workers, tasks, machines, vehicles, parsed, OptimizationOptions(max_time_seconds=max_solver_seconds))
    database = PlanningDatabase(settings.database_url)
    identifier = database.create_schedule(request_text, result.to_dict(), actor)
    return {"schedule_id": identifier, "schedule": result.to_dict(), "approval_status": "pending"}


def queue_for(settings: Settings | None = None) -> Queue:
    config = settings or get_settings()
    return Queue("planning", connection=Redis.from_url(config.redis_url), default_timeout=config.job_timeout_seconds)
