from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .data import load_workbook
from .database import PlanningDatabase
from .intent import IntentDecision, route_request
from .llm import answer_general_question, answer_workspace_question, explain_schedule, understand_request
from .local_llm import LocalLLM
from .jobs import queue_for
from .middleware import RequestControlsMiddleware
from .observability import SOLVER_DURATION, install_observability
from .rag import Passage, WorkspaceIndex
from .responses import compose_response, source_payload
from .scheduler import OptimizationOptions, create_schedule
from .security import Principal, configure_auth, current_principal, issue_token, require_roles, verify_password
from .settings import get_settings

from redis import Redis
from rq.job import Job


load_dotenv()
settings = get_settings()


def _workbook_path() -> Path:
    return Path(os.getenv("PLANNING_WORKBOOK", str(settings.planning_workbook))).resolve()


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8_000)
    history: list[HistoryItem] = Field(default_factory=list, max_length=8)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)


class ScheduleRequest(BaseModel):
    request: str = Field(min_length=1, max_length=8_000)
    max_solver_seconds: float = Field(default=30.0, gt=0, le=300)


class ReviewRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str = Field(default="", max_length=2_000)


class AppState:
    index: WorkspaceIndex | None = None
    client: LocalLLM | None = None
    indexed_at: float | None = None
    chunk_count: int = 0
    lock = asyncio.Lock()
    database: PlanningDatabase | None = None


state = AppState()


def _settings() -> tuple[Path, str, str]:
    workspace = Path(settings.planning_workspace).resolve(strict=True)
    llm_url = settings.local_llm_base_url
    model = settings.local_llm_model
    return workspace, llm_url, model


async def _build_index() -> None:
    workspace, _, _ = _settings()
    new_index = WorkspaceIndex(workspace)
    count = await asyncio.to_thread(new_index.build)
    state.index = new_index
    state.chunk_count = count
    state.indexed_at = time.time()


@asynccontextmanager
async def lifespan(_: FastAPI):
    _, llm_url, model = _settings()
    state.client = LocalLLM(llm_url, model)
    state.database = PlanningDatabase(settings.database_url)
    configure_auth(state.database)
    await _build_index()
    yield


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "X-Request-ID"])
app.add_middleware(RequestControlsMiddleware, max_request_bytes=settings.max_request_bytes, rate_limit_per_minute=settings.rate_limit_per_minute, redis_url=settings.redis_url)
install_observability(app, settings.otel_exporter_otlp_endpoint)


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready")
async def ready() -> dict[str, object]:
    checks = {"database": False, "retrieval": state.index is not None, "llm_configured": state.client is not None}
    try:
        checks["database"] = bool(state.database and state.database.ping())
    except Exception:
        pass
    if not all(checks.values()):
        raise HTTPException(503, detail=checks)
    return {"status": "ready", "checks": checks}


@app.get("/api/status")
async def status() -> dict[str, object]:
    workspace, _, model = _settings()
    return {
        "application": settings.app_name,
        "ready": state.index is not None and state.client is not None,
        "model": model,
        "workspace": workspace.name,
        "chunks": state.chunk_count,
        "indexed_at": state.indexed_at,
        "skipped": len(state.index.skipped) if state.index else 0,
        "privacy": "loopback-only",
        "retrieval": "hybrid-bm25-dense-reranked" if state.index and state.index.semantic_ready else "bm25-fallback",
        "semantic_ready": bool(state.index and state.index.semantic_ready),
        "semantic_error": state.index.semantic_error if state.index else None,
        "optimizer": "OR-Tools CP-SAT",
        "authentication_enabled": settings.auth_enabled,
        "environment": settings.environment,
    }


@app.post("/api/reindex")
async def reindex(_: Principal = Depends(require_roles("admin", "planner"))) -> dict[str, object]:
    if state.lock.locked():
        raise HTTPException(409, "Indexing is already in progress")
    async with state.lock:
        started = time.perf_counter()
        await _build_index()
    return {"chunks": state.chunk_count, "elapsed_seconds": round(time.perf_counter() - started, 3)}


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest, principal: Principal = Depends(current_principal)) -> StreamingResponse:
    if state.index is None or state.client is None:
        raise HTTPException(503, "Assistant is still starting")
    if state.database:
        state.database.audit(principal.username, "CHAT_QUESTION", "workspace", None, {"question_length": len(request.question)})
    return StreamingResponse(_event_stream(request, principal), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
    })


@app.post("/api/auth/login")
async def login(request: LoginRequest) -> dict[str, object]:
    if not settings.auth_enabled:
        return {"token": "local-auth-disabled", "username": "local-user", "role": "admin"}
    if state.database is None:
        raise HTTPException(503, "Database is not ready")
    user = state.database.get_user(request.username)
    if user is None or not verify_password(request.password, user["password_hash"]):
        state.database.audit(request.username, "LOGIN_FAILED", "user", request.username, {})
        raise HTTPException(401, "Invalid username or password")
    principal = Principal(user["username"], user["role"])
    token = issue_token(principal, settings.app_secret_key)
    state.database.audit(principal.username, "LOGIN_SUCCESS", "user", principal.username, {})
    return {"token": token, "username": principal.username, "role": principal.role}


@app.get("/api/auth/me")
async def me(principal: Principal = Depends(current_principal)) -> dict[str, str]:
    return {"username": principal.username, "role": principal.role}


@app.post("/api/schedules")
async def optimize_schedule(request: ScheduleRequest, principal: Principal = Depends(require_roles("admin", "planner"))) -> dict[str, object]:
    if state.client is None or state.database is None:
        raise HTTPException(503, "Application is still starting")
    workbook = _workbook_path()
    if not workbook.is_file():
        raise HTTPException(404, f"Planning workbook not found: {workbook.name}")
    try:
        started = time.perf_counter()
        constraint_started = time.perf_counter()
        parsed = await asyncio.to_thread(understand_request, state.client, request.request)
        constraint_seconds = time.perf_counter() - constraint_started
        workers, tasks, machines, vehicles = await asyncio.to_thread(load_workbook, workbook)
        solver_started = time.perf_counter()
        result = await asyncio.to_thread(
            create_schedule, workers, tasks, machines, vehicles, parsed,
            OptimizationOptions(max_time_seconds=request.max_solver_seconds),
        )
        solver_seconds = time.perf_counter() - solver_started
        SOLVER_DURATION.observe(solver_seconds)
        identifier = state.database.create_schedule(request.request, result.to_dict(), principal.username)
        response = compose_response(
            "Schedule created successfully. It is a draft until a supervisor approves it.",
            IntentDecision(planning=True, method="schedule-endpoint"), [],
            {"constraint_parser_seconds": round(constraint_seconds, 3), "solver_seconds": round(solver_seconds, 3)},
            result, identifier,
        )
        response["timing"]["total_seconds"] = round(time.perf_counter() - started, 3)
        return response
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(422, str(error)) from error


@app.post("/api/jobs/schedules", status_code=202)
async def enqueue_schedule(request: ScheduleRequest, principal: Principal = Depends(require_roles("admin", "planner"))) -> dict[str, str]:
    try:
        job = queue_for(settings).enqueue("planning_agent.jobs.schedule_job", request.request, principal.username, request.max_solver_seconds)
    except Exception as error:
        raise HTTPException(503, f"Planning queue is unavailable: {error}") from error
    return {"job_id": job.id, "status": "queued"}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str, _: Principal = Depends(current_principal)) -> dict[str, object]:
    try:
        job = Job.fetch(job_id, connection=Redis.from_url(settings.redis_url))
    except Exception as error:
        raise HTTPException(404, "Job not found") from error
    return {"job_id": job.id, "status": job.get_status(refresh=True), "result": job.result if job.is_finished else None, "error": job.exc_info[-1000:] if job.is_failed and job.exc_info else None}


@app.get("/api/schedules")
async def schedule_history(principal: Principal = Depends(current_principal)) -> list[dict[str, object]]:
    if state.database is None:
        raise HTTPException(503, "Database is not ready")
    return state.database.list_schedules()


@app.post("/api/schedules/{identifier}/review")
async def review_schedule(identifier: str, request: ReviewRequest, principal: Principal = Depends(require_roles("admin", "planner"))) -> dict[str, str]:
    if state.database is None:
        raise HTTPException(503, "Database is not ready")
    try:
        state.database.review_schedule(identifier, request.decision, principal.username, request.comment)
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    return {"id": identifier, "status": request.decision}


async def _event_stream(request: ChatRequest, principal: Principal) -> AsyncIterator[str]:
    started = time.perf_counter()
    try:
        timings: dict[str, float] = {}
        yield _sse("status", {"stage": "routing", "message": "Understanding the request"})
        mark = time.perf_counter()
        intents = await asyncio.to_thread(route_request, state.client, request.question)  # type: ignore[arg-type]
        timings["routing_seconds"] = round(time.perf_counter() - mark, 3)
        yield _sse("intent", intents.to_dict())

        passages: list[Passage] = []
        schedule = None
        schedule_id = None
        workbook = None
        if intents.planning:
            if principal.role not in {"admin", "planner"}:
                raise PermissionError("Planning requires the planner or admin role.")
            workbook = _workbook_path()
            if not workbook.is_file():
                raise FileNotFoundError(f"Planning workbook not found: {workbook.name}")

        # Once routing is known these jobs are independent: semantic retrieval
        # uses CPU, constraint parsing uses local Kimi, and Excel loading is I/O.
        # Running them together reduces latency without adding GPU workloads.
        preparation_started = time.perf_counter()
        preparation: dict[str, asyncio.Task] = {}
        if intents.rag:
            yield _sse("status", {"stage": "preparing", "message": "Searching files and preparing the plan in parallel" if intents.planning else "Searching approved local files"})
            preparation["retrieval"] = asyncio.create_task(_timed_to_thread(state.index.search, request.question, 5, 0.04))  # type: ignore[union-attr]
        if intents.planning:
            if not intents.rag:
                yield _sse("status", {"stage": "parsing", "message": "Parsing planning constraints"})
            preparation["constraints"] = asyncio.create_task(_timed_to_thread(understand_request, state.client, request.question))  # type: ignore[arg-type]
            preparation["workbook"] = asyncio.create_task(_timed_to_thread(load_workbook, workbook))
        prepared = dict(zip(preparation, await asyncio.gather(*preparation.values()))) if preparation else {}
        timings["parallel_preparation_seconds"] = round(time.perf_counter() - preparation_started, 3)

        if intents.rag:
            passages, timings["retrieval_seconds"] = prepared["retrieval"]
            yield _sse("sources", {"items": [source_payload(p) for p in passages]})
        if intents.planning:
            parsed, timings["constraint_parser_seconds"] = prepared["constraints"]
            (workers, tasks, machines, vehicles), timings["workbook_load_seconds"] = prepared["workbook"]
            yield _sse("status", {"stage": "optimizing", "message": "Optimizing the draft schedule"})
            mark = time.perf_counter()
            schedule = await asyncio.to_thread(create_schedule, workers, tasks, machines, vehicles, parsed)
            timings["solver_seconds"] = round(time.perf_counter() - mark, 3)
            SOLVER_DURATION.observe(timings["solver_seconds"])
            schedule_id = state.database.create_schedule(request.question, schedule.to_dict(), principal.username)  # type: ignore[union-attr]

        yield _sse("status", {"stage": "thinking", "message": "Kimi is composing the response"})
        mark = time.perf_counter()
        history = [item.model_dump() for item in request.history]
        if schedule is not None:
            call = (explain_schedule, state.client, request.question, schedule, passages)
        elif intents.rag:
            call = (answer_workspace_question, state.client, request.question, passages, history)
        else:
            call = (answer_general_question, state.client, request.question, history)
        task = asyncio.create_task(asyncio.to_thread(*call))
        while not task.done():
            elapsed = time.perf_counter() - started
            timeout = 1.0 if elapsed >= 9.0 else min(9.0 - elapsed, 1.0)
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=max(timeout, 0.1))
            except TimeoutError:
                if elapsed >= 9.0:
                    yield _sse("progress", {"elapsed_seconds": int(time.perf_counter() - started)})
        answer = await task
        timings["llm_seconds"] = round(time.perf_counter() - mark, 3)
        elapsed = time.perf_counter() - started
        response = compose_response(answer, intents, passages, timings, schedule, schedule_id)
        response["timing"]["total_seconds"] = round(elapsed, 3)
        response["elapsed_seconds"] = round(elapsed, 2)
        response["show_timing"] = elapsed >= 10.0
        if state.database:
            state.database.audit(principal.username, "CHAT_COMPLETED", "workspace", schedule_id, {
                "intents": intents.to_dict(), "source_count": len(passages), "elapsed_seconds": round(elapsed, 3),
            })
        yield _sse("complete", response)
    except Exception as error:
        yield _sse("error", {"message": str(error), "elapsed_seconds": round(time.perf_counter() - started, 2)})


async def _timed_to_thread(function, *args):
    started = time.perf_counter()
    result = await asyncio.to_thread(function, *args)
    return result, round(time.perf_counter() - started, 3)


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


frontend = Path(__file__).resolve().parents[1] / "web" / "dist"
if frontend.is_dir():
    app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        candidate = (frontend / path).resolve()
        if path and candidate.is_relative_to(frontend) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend / "index.html")
