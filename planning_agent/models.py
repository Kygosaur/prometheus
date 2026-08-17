from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class TimeWindow:
    start_minute: int
    end_minute: int
    label: str = "available"


@dataclass(frozen=True)
class Worker:
    name: str
    skill: str
    available: bool = True
    skills: tuple[str, ...] = ()
    certifications: tuple[str, ...] = ()
    availability: tuple[TimeWindow, ...] = ()
    shift: str | None = None
    location: str | None = None
    cost_per_hour: float = 0.0
    current_workload_hours: float = 0.0

    @property
    def all_skills(self) -> frozenset[str]:
        return frozenset((self.skill, *self.skills))


@dataclass(frozen=True)
class Machine:
    name: str
    machine_type: str
    available: bool = True
    capabilities: tuple[str, ...] = ()
    availability: tuple[TimeWindow, ...] = ()
    maintenance: tuple[TimeWindow, ...] = ()
    location: str | None = None
    operating_cost_per_hour: float = 0.0


@dataclass(frozen=True)
class Vehicle:
    name: str
    vehicle_type: str
    available: bool = True
    capabilities: tuple[str, ...] = ()
    availability: tuple[TimeWindow, ...] = ()
    maintenance: tuple[TimeWindow, ...] = ()
    location: str | None = None
    operating_cost_per_hour: float = 0.0


@dataclass(frozen=True)
class Task:
    name: str
    duration_hours: float
    priority: str
    deadline_hours: float | None
    required_skill: str
    workers_needed: int
    machine_type: str
    predecessors: tuple[str, ...] = ()
    vehicle_type: str | None = None
    location: str | None = None
    required_skills: tuple[str, ...] = ()
    required_certifications: tuple[str, ...] = ()
    machine_requirements: tuple[str, ...] = ()
    vehicle_requirements: tuple[str, ...] = ()
    setup_requirements: tuple[str, ...] = ()
    setup_hours: float = 0.0
    travel_hours: float = 0.0

    @property
    def total_duration_hours(self) -> float:
        return self.setup_hours + self.travel_hours + self.duration_hours


@dataclass(frozen=True)
class PlanningRequest:
    blocked_machines: tuple[str, ...] = ()
    blocked_workers: tuple[str, ...] = ()
    blocked_vehicles: tuple[str, ...] = ()
    safety_question: str | None = None


@dataclass(frozen=True)
class ScheduledTask:
    task: str
    start_hour: float
    end_hour: float
    workers: tuple[str, ...]
    machine: str
    vehicle: str | None
    priority: str
    deadline_hour: float | None
    deadline_met: bool | None
    selection_reason: str
    start_time: str | None = None
    end_time: str | None = None
    work_duration_hours: float | None = None
    setup_hours: float = 0.0
    travel_hours: float = 0.0
    estimated_cost: float = 0.0


@dataclass(frozen=True)
class UnscheduledTask:
    task: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScheduleResult:
    scheduled: tuple[ScheduledTask, ...]
    unscheduled: tuple[UnscheduledTask, ...]
    makespan_hours: float
    unavailable_resources: dict[str, tuple[str, ...]]
    solver: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
