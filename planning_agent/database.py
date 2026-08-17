from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, MetaData, String, Table, Text, create_engine, desc, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

metadata = MetaData()
users = Table("users", metadata, Column("username", String(100), primary_key=True), Column("password_hash", Text, nullable=False), Column("role", String(20), nullable=False), Column("active", Boolean, nullable=False, default=True), Column("created_at", DateTime(timezone=True), nullable=False))
schedule_runs = Table("schedule_runs", metadata, Column("id", String(36), primary_key=True), Column("status", String(20), nullable=False), Column("request_text", Text, nullable=False), Column("result_json", JSON, nullable=False), Column("created_by", String(100), nullable=False), Column("created_at", DateTime(timezone=True), nullable=False), Column("reviewed_by", String(100)), Column("reviewed_at", DateTime(timezone=True)), Column("review_comment", Text))
audit_events = Table("audit_events", metadata, Column("id", Integer, primary_key=True, autoincrement=True), Column("timestamp", DateTime(timezone=True), nullable=False), Column("actor", String(100), nullable=False), Column("action", String(100), nullable=False), Column("entity_type", String(50), nullable=False), Column("entity_id", String(100)), Column("details_json", JSON, nullable=False))
chat_runs = Table("chat_runs", metadata, Column("id", String(36), primary_key=True), Column("actor", String(100), nullable=False), Column("question", Text, nullable=False), Column("intents_json", JSON), Column("response_json", JSON), Column("status", String(20), nullable=False), Column("request_id", String(100)), Column("created_at", DateTime(timezone=True), nullable=False), Column("completed_at", DateTime(timezone=True)))


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PlanningDatabase:
    """SQLite for local development and PostgreSQL for production through one API."""

    def __init__(self, url: str | Path, create_schema: bool = True):
        value = str(url)
        if "://" not in value:
            path = Path(value)
            path.parent.mkdir(parents=True, exist_ok=True)
            value = f"sqlite:///{path.as_posix()}"
        self.url = value
        engine_options = {"pool_pre_ping": True}
        if value.startswith("sqlite"):
            engine_options["poolclass"] = NullPool
        self.engine: Engine = create_engine(value, **engine_options)
        if create_schema:
            metadata.create_all(self.engine)

    def ping(self) -> bool:
        with self.engine.connect() as connection:
            connection.execute(select(1))
        return True

    def get_user(self, username: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(users).where(users.c.username == username, users.c.active.is_(True))).mappings().first()
        return dict(row) if row else None

    def upsert_user(self, username: str, password_hash: str, role: str) -> None:
        if role not in {"admin", "planner", "viewer"}:
            raise ValueError("Invalid role")
        with self.engine.begin() as connection:
            existing = connection.execute(select(users.c.username).where(users.c.username == username)).first()
            values = {"password_hash": password_hash, "role": role, "active": True}
            if existing:
                connection.execute(update(users).where(users.c.username == username).values(**values))
            else:
                connection.execute(users.insert().values(username=username, created_at=_now(), **values))
        self.audit(username, "USER_UPSERT", "user", username, {"role": role})

    def create_schedule(self, request_text: str, result: dict[str, Any], actor: str) -> str:
        identifier = str(uuid.uuid4())
        with self.engine.begin() as connection:
            connection.execute(schedule_runs.insert().values(id=identifier, status="draft", request_text=request_text, result_json=result, created_by=actor, created_at=_now()))
        self.audit(actor, "SCHEDULE_CREATED", "schedule", identifier, {"status": "draft"})
        return identifier

    def review_schedule(self, identifier: str, decision: str, actor: str, comment: str = "") -> None:
        if decision not in {"approved", "rejected"}:
            raise ValueError("Decision must be approved or rejected")
        with self.engine.begin() as connection:
            result = connection.execute(update(schedule_runs).where(schedule_runs.c.id == identifier, schedule_runs.c.status == "draft").values(status=decision, reviewed_by=actor, reviewed_at=_now(), review_comment=comment))
            if result.rowcount != 1:
                raise KeyError("Draft schedule not found")
        self.audit(actor, f"SCHEDULE_{decision.upper()}", "schedule", identifier, {"comment": comment})

    def list_schedules(self, limit: int = 50) -> list[dict[str, Any]]:
        statement = select(schedule_runs).order_by(desc(schedule_runs.c.created_at)).limit(max(1, min(limit, 200)))
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [{**dict(row), "result": row["result_json"]} for row in rows]

    def start_chat(self, actor: str, question: str, request_id: str | None = None) -> str:
        identifier = str(uuid.uuid4())
        with self.engine.begin() as connection:
            connection.execute(chat_runs.insert().values(id=identifier, actor=actor, question=question, status="running", request_id=request_id, created_at=_now()))
        return identifier

    def finish_chat(self, identifier: str, status: str, intents: dict[str, Any] | None = None, response: dict[str, Any] | None = None) -> None:
        with self.engine.begin() as connection:
            connection.execute(update(chat_runs).where(chat_runs.c.id == identifier).values(status=status, intents_json=intents, response_json=response, completed_at=_now()))

    def audit(self, actor: str, action: str, entity_type: str, entity_id: str | None, details: dict[str, Any]) -> None:
        with self.engine.begin() as connection:
            connection.execute(audit_events.insert().values(timestamp=_now(), actor=actor, action=action, entity_type=entity_type, entity_id=entity_id, details_json=details))
