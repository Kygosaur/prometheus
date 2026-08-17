from __future__ import annotations

from pathlib import Path

import pandas as pd

from .calendars import parse_calendar
from .models import Machine, Task, Vehicle, Worker


PRIORITIES = {"critical", "high", "medium", "low"}


def _required_columns(frame: pd.DataFrame, sheet: str, columns: set[str]) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"Sheet {sheet!r} is missing columns: {sorted(missing)}")


def _text(value: object, field: str) -> str:
    if pd.isna(value) or not str(value).strip():
        raise ValueError(f"{field} must not be empty")
    return str(value).strip()


def _boolean(value: object, field: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"{field} must be a boolean, got {value!r}")


def load_workbook(path: str | Path) -> tuple[list[Worker], list[Task], list[Machine], list[Vehicle]]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Planning workbook not found: {path}")

    # ExcelFile keeps an open file handle on Windows, so close it before any
    # validation can raise and before callers try to move/delete the workbook.
    with pd.ExcelFile(path) as book:
        for sheet in ("Workers", "Tasks", "Machines"):
            if sheet not in book.sheet_names:
                raise ValueError(f"Workbook is missing required sheet {sheet!r}")

        workers_df = pd.read_excel(book, "Workers")
        tasks_df = pd.read_excel(book, "Tasks")
        machines_df = pd.read_excel(book, "Machines")
        vehicles_df = pd.read_excel(book, "Vehicles") if "Vehicles" in book.sheet_names else pd.DataFrame()

    _required_columns(workers_df, "Workers", {"Worker", "Available"})
    _required_columns(machines_df, "Machines", {"Machine", "Type", "Available"})
    _required_columns(tasks_df, "Tasks", {"Task", "Duration_Hours", "Priority", "Deadline_Days", "Workers_Needed"})

    workers: list[Worker] = []
    for row in workers_df.to_dict("records"):
        calendar, _ = parse_calendar(_optional_text(row.get("Calendar")))
        skills = _list(row.get("Skills"))
        primary_skill = _optional_text(row.get("Skill")) or (skills[0] if skills else "")
        if not primary_skill:
            raise ValueError(f"Worker {row.get('Worker')!r} must have at least one skill")
        workers.append(Worker(
            name=_text(row["Worker"], "Worker"), skill=primary_skill.casefold(),
            available=_boolean(row["Available"], "Worker.Available"), skills=tuple(value.casefold() for value in skills),
            certifications=tuple(value.casefold() for value in _list(row.get("Certifications"))), availability=calendar,
            shift=_optional_text(row.get("Shift")), location=_casefold_optional(row.get("Location")),
            cost_per_hour=_nonnegative(row.get("Cost_Per_Hour"), "Worker.Cost_Per_Hour"),
            current_workload_hours=_nonnegative(row.get("Current_Workload_Hours"), "Worker.Current_Workload_Hours"),
        ))

    machines: list[Machine] = []
    for row in machines_df.to_dict("records"):
        calendar, maintenance = parse_calendar(_optional_text(row.get("Calendar")))
        machines.append(Machine(
            name=_text(row["Machine"], "Machine"), machine_type=_text(row["Type"], "Machine.Type").casefold(),
            available=_boolean(row["Available"], "Machine.Available"),
            capabilities=tuple(value.casefold() for value in _list(row.get("Capabilities"))),
            availability=calendar, maintenance=maintenance, location=_casefold_optional(row.get("Location")),
            operating_cost_per_hour=_nonnegative(row.get("Operating_Cost_Per_Hour"), "Machine.Operating_Cost_Per_Hour"),
        ))

    vehicles: list[Vehicle] = []
    if not vehicles_df.empty:
        _required_columns(vehicles_df, "Vehicles", {"Vehicle", "Type", "Available"})
        for row in vehicles_df.to_dict("records"):
            calendar, maintenance = parse_calendar(_optional_text(row.get("Calendar")))
            vehicles.append(Vehicle(
                name=_text(row["Vehicle"], "Vehicle"), vehicle_type=_text(row["Type"], "Vehicle.Type").casefold(),
                available=_boolean(row["Available"], "Vehicle.Available"),
                capabilities=tuple(value.casefold() for value in _list(row.get("Capabilities"))), availability=calendar,
                maintenance=maintenance, location=_casefold_optional(row.get("Location")),
                operating_cost_per_hour=_nonnegative(row.get("Operating_Cost_Per_Hour"), "Vehicle.Operating_Cost_Per_Hour"),
            ))

    tasks: list[Task] = []
    for row in tasks_df.to_dict("records"):
        priority = _text(row["Priority"], "Task.Priority").casefold()
        if priority not in PRIORITIES:
            raise ValueError(f"Unknown priority {priority!r}; expected one of {sorted(PRIORITIES)}")
        duration = float(row["Duration_Hours"])
        workers_needed_float = float(row["Workers_Needed"])
        setup_hours = _nonnegative(row.get("Setup_Hours"), "Task.Setup_Hours")
        travel_hours = _nonnegative(row.get("Travel_Hours"), "Task.Travel_Hours")
        if duration <= 0 or not workers_needed_float.is_integer() or workers_needed_float < 1:
            raise ValueError(f"Invalid duration or worker count for task {row['Task']!r}")
        deadline = None if pd.isna(row["Deadline_Days"]) else float(row["Deadline_Days"]) * 24
        predecessor_value = row.get("Predecessors", "")
        predecessors = () if pd.isna(predecessor_value) else tuple(x.strip() for x in str(predecessor_value).split(",") if x.strip())
        vehicle_value = row.get("Vehicle_Type")
        vehicle_type = None if vehicle_value is None or pd.isna(vehicle_value) or not str(vehicle_value).strip() else str(vehicle_value).strip().casefold()
        required_skills = _list(row.get("Required_Skills"))
        required_skill = _optional_text(row.get("Required_Skill")) or (required_skills[0] if required_skills else "")
        machine_requirements = _list(row.get("Machine_Requirements"))
        machine_type = _optional_text(row.get("Machine_Type")) or (machine_requirements[0] if machine_requirements else "")
        tasks.append(Task(
            name=_text(row["Task"], "Task"), duration_hours=duration,
            priority=priority, deadline_hours=deadline,
            required_skill=required_skill.casefold(),
            workers_needed=int(workers_needed_float), machine_type=machine_type.casefold(),
            predecessors=predecessors, vehicle_type=vehicle_type,
            location=_casefold_optional(row.get("Location")),
            required_skills=tuple(value.casefold() for value in required_skills),
            required_certifications=tuple(value.casefold() for value in _list(row.get("Required_Certifications"))),
            machine_requirements=tuple(value.casefold() for value in machine_requirements),
            vehicle_requirements=tuple(value.casefold() for value in _list(row.get("Vehicle_Requirements"))),
            setup_requirements=tuple(value.casefold() for value in _list(row.get("Setup_Requirements"))),
            setup_hours=setup_hours, travel_hours=travel_hours,
        ))

    _validate_unique([w.name for w in workers], "worker")
    _validate_unique([m.name for m in machines], "machine")
    _validate_unique([v.name for v in vehicles], "vehicle")
    _validate_unique([t.name for t in tasks], "task")
    known_tasks = {t.name for t in tasks}
    for task in tasks:
        unknown = set(task.predecessors) - known_tasks
        if unknown:
            raise ValueError(f"Task {task.name!r} has unknown predecessors: {sorted(unknown)}")
    return workers, tasks, machines, vehicles


def _validate_unique(names: list[str], kind: str) -> None:
    folded = [name.casefold() for name in names]
    duplicates = sorted({names[i] for i, value in enumerate(folded) if folded.count(value) > 1})
    if duplicates:
        raise ValueError(f"Duplicate {kind} identifiers: {duplicates}")


def _optional_text(value: object) -> str | None:
    return None if value is None or pd.isna(value) or not str(value).strip() else str(value).strip()


def _casefold_optional(value: object) -> str | None:
    text = _optional_text(value)
    return text.casefold() if text else None


def _list(value: object) -> list[str]:
    text = _optional_text(value)
    return [item.strip() for item in text.split(",") if item.strip()] if text else []


def _nonnegative(value: object, field: str) -> float:
    if value is None or pd.isna(value) or value == "":
        return 0.0
    number = float(value)
    if number < 0:
        raise ValueError(f"{field} must not be negative")
    return number
