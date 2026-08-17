from __future__ import annotations

import os
import time
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .calendars import WEEK_MINUTES, format_week_minute
from .models import Machine, PlanningRequest, ScheduledTask, ScheduleResult, Task, UnscheduledTask, Vehicle, Worker


PRIORITY_WEIGHT = {"critical": 10, "high": 6, "medium": 3, "low": 1}
MINUTES_PER_HOUR = 60


@dataclass(frozen=True)
class OptimizationOptions:
    max_time_seconds: float = 30.0
    # Leave CPU capacity for Kimi support services, retrieval, and the desktop.
    num_search_workers: int = max(1, min(int(os.getenv("ORTOOLS_SEARCH_WORKERS", "4")), os.cpu_count() or 1))
    random_seed: int = 42


def create_schedule(
    workers: list[Worker],
    tasks: list[Task],
    machines: list[Machine],
    vehicles: list[Vehicle] | None = None,
    request: PlanningRequest | None = None,
    options: OptimizationOptions | None = None,
) -> ScheduleResult:
    """Create an optimized resource-feasible schedule using OR-Tools CP-SAT."""
    started = time.perf_counter()
    vehicles = vehicles or []
    request = request or PlanningRequest()
    options = options or OptimizationOptions()
    _validate_options(options)

    blocked_machines = {x.casefold() for x in request.blocked_machines}
    blocked_workers = {x.casefold() for x in request.blocked_workers}
    blocked_vehicles = {x.casefold() for x in request.blocked_vehicles}
    usable_workers = [w for w in workers if w.available and w.name.casefold() not in blocked_workers]
    usable_machines = [m for m in machines if m.available and m.name.casefold() not in blocked_machines]
    usable_vehicles = [v for v in vehicles if v.available and v.name.casefold() not in blocked_vehicles]

    worker_candidates = {t.name: [w for w in usable_workers if _worker_matches(w, t)] for t in tasks}
    machine_candidates = {t.name: [m for m in usable_machines if _machine_matches(m, t)] for t in tasks}
    vehicle_candidates = {t.name: [v for v in usable_vehicles if _vehicle_matches(v, t)] for t in tasks}
    unscheduled: list[UnscheduledTask] = []
    excluded: set[str] = set()

    for task in tasks:
        if len(worker_candidates[task.name]) < task.workers_needed:
            excluded.add(task.name)
            unscheduled.append(UnscheduledTask(task.name, "Insufficient available skilled workers", {
                "needed": task.workers_needed, "available": len(worker_candidates[task.name]), "skill": task.required_skill,
            }))
        elif not machine_candidates[task.name]:
            excluded.add(task.name)
            unscheduled.append(UnscheduledTask(task.name, "No available compatible machine", {"machine_type": task.machine_type}))
        elif task.vehicle_type and not vehicle_candidates[task.name]:
            excluded.add(task.name)
            unscheduled.append(UnscheduledTask(task.name, "No available compatible vehicle", {"vehicle_type": task.vehicle_type}))

    # A task cannot be optimized if one of its predecessors cannot be scheduled.
    changed = True
    while changed:
        changed = False
        for task in tasks:
            failed = [p for p in task.predecessors if p in excluded]
            if task.name not in excluded and failed:
                excluded.add(task.name)
                unscheduled.append(UnscheduledTask(task.name, "Unscheduled predecessor", {"predecessors": failed}))
                changed = True

    active = [task for task in tasks if task.name not in excluded]
    cycle = _find_cycle(active)
    if cycle:
        cycle_set = set(cycle)
        for task in active:
            if task.name in cycle_set:
                unscheduled.append(UnscheduledTask(task.name, "Precedence cycle", {"cycle": cycle}))
        excluded.update(cycle_set)
        active = [task for task in active if task.name not in excluded]

    unavailable = {
        "workers": tuple(w.name for w in workers if not w.available or w.name.casefold() in blocked_workers),
        "machines": tuple(m.name for m in machines if not m.available or m.name.casefold() in blocked_machines),
        "vehicles": tuple(v.name for v in vehicles if not v.available or v.name.casefold() in blocked_vehicles),
    }
    if not active:
        return ScheduleResult((), tuple(unscheduled), 0.0, unavailable, {
            "engine": "OR-Tools CP-SAT", "status": "NO_ACTIVE_TASKS", "wall_time_seconds": round(time.perf_counter() - started, 4),
        })

    model = cp_model.CpModel()
    durations = {t.name: _minutes(t.total_duration_hours) for t in active}
    latest_deadline = max((_minutes(t.deadline_hours) for t in active if t.deadline_hours is not None), default=0)
    horizon = max(WEEK_MINUTES, sum(durations.values()), latest_deadline)
    starts = {t.name: model.new_int_var(0, horizon, f"start_{_safe(t.name)}") for t in active}
    ends = {t.name: model.new_int_var(0, horizon, f"end_{_safe(t.name)}") for t in active}
    intervals = {
        t.name: model.new_interval_var(starts[t.name], durations[t.name], ends[t.name], f"task_{_safe(t.name)}") for t in active
    }

    active_names = {task.name for task in active}
    for task in active:
        for predecessor in task.predecessors:
            if predecessor in active_names:
                model.add(starts[task.name] >= ends[predecessor])

    worker_assignments: dict[tuple[str, str], cp_model.IntVar] = {}
    machine_assignments: dict[tuple[str, str], cp_model.IntVar] = {}
    vehicle_assignments: dict[tuple[str, str], cp_model.IntVar] = {}
    worker_intervals: dict[str, list[cp_model.IntervalVar]] = {w.name: [] for w in usable_workers}
    machine_intervals: dict[str, list[cp_model.IntervalVar]] = {m.name: [] for m in usable_machines}
    vehicle_intervals: dict[str, list[cp_model.IntervalVar]] = {v.name: [] for v in usable_vehicles}

    for machine in usable_machines:
        for number, window in enumerate(machine.maintenance):
            duration = min(window.end_minute, horizon) - window.start_minute
            if duration > 0 and window.start_minute < horizon:
                machine_intervals[machine.name].append(model.new_fixed_size_interval_var(window.start_minute, duration, f"maintenance_{_safe(machine.name)}_{number}"))
    for vehicle in usable_vehicles:
        for number, window in enumerate(vehicle.maintenance):
            duration = min(window.end_minute, horizon) - window.start_minute
            if duration > 0 and window.start_minute < horizon:
                vehicle_intervals[vehicle.name].append(model.new_fixed_size_interval_var(window.start_minute, duration, f"maintenance_{_safe(vehicle.name)}_{number}"))

    for task in active:
        worker_vars = []
        for worker in worker_candidates[task.name]:
            assigned = model.new_bool_var(f"worker_{_safe(task.name)}_{_safe(worker.name)}")
            optional = model.new_optional_interval_var(starts[task.name], durations[task.name], ends[task.name], assigned, f"wi_{_safe(task.name)}_{_safe(worker.name)}")
            worker_assignments[(task.name, worker.name)] = assigned
            worker_intervals[worker.name].append(optional)
            _constrain_to_calendar(model, starts[task.name], ends[task.name], assigned, worker.availability, horizon, f"wc_{_safe(task.name)}_{_safe(worker.name)}")
            worker_vars.append(assigned)
        model.add(sum(worker_vars) == task.workers_needed)

        machine_vars = []
        for machine in machine_candidates[task.name]:
            assigned = model.new_bool_var(f"machine_{_safe(task.name)}_{_safe(machine.name)}")
            optional = model.new_optional_interval_var(starts[task.name], durations[task.name], ends[task.name], assigned, f"mi_{_safe(task.name)}_{_safe(machine.name)}")
            machine_assignments[(task.name, machine.name)] = assigned
            machine_intervals[machine.name].append(optional)
            _constrain_to_calendar(model, starts[task.name], ends[task.name], assigned, machine.availability, horizon, f"mc_{_safe(task.name)}_{_safe(machine.name)}")
            machine_vars.append(assigned)
        model.add(sum(machine_vars) == 1)

        if task.vehicle_type:
            vehicle_vars = []
            for vehicle in vehicle_candidates[task.name]:
                assigned = model.new_bool_var(f"vehicle_{_safe(task.name)}_{_safe(vehicle.name)}")
                optional = model.new_optional_interval_var(starts[task.name], durations[task.name], ends[task.name], assigned, f"vi_{_safe(task.name)}_{_safe(vehicle.name)}")
                vehicle_assignments[(task.name, vehicle.name)] = assigned
                vehicle_intervals[vehicle.name].append(optional)
                _constrain_to_calendar(model, starts[task.name], ends[task.name], assigned, vehicle.availability, horizon, f"vc_{_safe(task.name)}_{_safe(vehicle.name)}")
                vehicle_vars.append(assigned)
            model.add(sum(vehicle_vars) == 1)

    for resource_intervals in (*worker_intervals.values(), *machine_intervals.values(), *vehicle_intervals.values()):
        if len(resource_intervals) > 1:
            model.add_no_overlap(resource_intervals)

    makespan = model.new_int_var(0, horizon, "makespan")
    model.add_max_equality(makespan, [ends[t.name] for t in active])
    objective_terms: list[cp_model.LinearExpr] = [makespan * 10]
    for task in active:
        if task.deadline_hours is not None:
            deadline = max(0, _minutes(task.deadline_hours))
            tardiness = model.new_int_var(0, horizon, f"tardiness_{_safe(task.name)}")
            model.add(tardiness >= ends[task.name] - deadline)
            objective_terms.append(tardiness * PRIORITY_WEIGHT[task.priority] * 100)
        objective_terms.append(starts[task.name] * PRIORITY_WEIGHT[task.priority])
        for worker in worker_candidates[task.name]:
            assignment_cost = round((worker.cost_per_hour * task.total_duration_hours + worker.current_workload_hours) * 10)
            if assignment_cost:
                objective_terms.append(worker_assignments[(task.name, worker.name)] * assignment_cost)
        for machine in machine_candidates[task.name]:
            assignment_cost = round(machine.operating_cost_per_hour * task.total_duration_hours * 10)
            if assignment_cost:
                objective_terms.append(machine_assignments[(task.name, machine.name)] * assignment_cost)
    model.minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = options.max_time_seconds
    solver.parameters.num_search_workers = options.num_search_workers
    solver.parameters.random_seed = options.random_seed
    status = solver.solve(model)
    status_name = solver.status_name(status)
    metadata = {
        "engine": "OR-Tools CP-SAT", "status": status_name,
        "optimal": status == cp_model.OPTIMAL, "objective_value": solver.objective_value if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
        "best_objective_bound": solver.best_objective_bound if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
        "wall_time_seconds": round(solver.wall_time, 4), "conflicts": solver.num_conflicts, "branches": solver.num_branches,
    }
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for task in active:
            unscheduled.append(UnscheduledTask(task.name, "Optimizer found no feasible schedule", {"solver_status": status_name}))
        return ScheduleResult((), tuple(unscheduled), 0.0, unavailable, metadata)

    scheduled: list[ScheduledTask] = []
    for task in active:
        selected_workers = tuple(sorted(w.name for w in worker_candidates[task.name] if solver.boolean_value(worker_assignments[(task.name, w.name)])))
        selected_machine = next(m.name for m in machine_candidates[task.name] if solver.boolean_value(machine_assignments[(task.name, m.name)]))
        selected_vehicle = None
        if task.vehicle_type:
            selected_vehicle = next(v.name for v in vehicle_candidates[task.name] if solver.boolean_value(vehicle_assignments[(task.name, v.name)]))
        start_hour = solver.value(starts[task.name]) / MINUTES_PER_HOUR
        end_hour = solver.value(ends[task.name]) / MINUTES_PER_HOUR
        deadline_met = None if task.deadline_hours is None else end_hour <= task.deadline_hours
        selected_worker_objects = [w for w in worker_candidates[task.name] if w.name in selected_workers]
        selected_machine_object = next(m for m in machine_candidates[task.name] if m.name == selected_machine)
        selected_vehicle_object = next((v for v in vehicle_candidates[task.name] if v.name == selected_vehicle), None)
        estimated_cost = task.total_duration_hours * (
            sum(worker.cost_per_hour for worker in selected_worker_objects)
            + selected_machine_object.operating_cost_per_hour
            + (selected_vehicle_object.operating_cost_per_hour if selected_vehicle_object else 0.0)
        )
        scheduled.append(ScheduledTask(
            task.name, start_hour, end_hour, selected_workers, selected_machine, selected_vehicle,
            task.priority, task.deadline_hours, deadline_met,
            "Selected by OR-Tools CP-SAT to minimize weighted deadline lateness and total makespan subject to resource and precedence constraints",
            start_time=format_week_minute(solver.value(starts[task.name])), end_time=format_week_minute(solver.value(ends[task.name])),
            work_duration_hours=task.duration_hours, setup_hours=task.setup_hours, travel_hours=task.travel_hours,
            estimated_cost=round(estimated_cost, 2),
        ))
    return ScheduleResult(tuple(sorted(scheduled, key=lambda item: (item.start_hour, item.task))), tuple(unscheduled), solver.value(makespan) / MINUTES_PER_HOUR, unavailable, metadata)


def _minutes(hours: float) -> int:
    return max(1, round(hours * MINUTES_PER_HOUR))


def _safe(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)


def _validate_options(options: OptimizationOptions) -> None:
    if options.max_time_seconds <= 0 or options.num_search_workers < 1:
        raise ValueError("Optimizer time and worker limits must be positive")


def _find_cycle(tasks: list[Task]) -> list[str]:
    task_names = {task.name for task in tasks}
    graph = {task.name: [p for p in task.predecessors if p in task_names] for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()
    path: list[str] = []

    def visit(node: str) -> list[str]:
        if node in visiting:
            start = path.index(node)
            return path[start:] + [node]
        if node in visited:
            return []
        visiting.add(node)
        path.append(node)
        for predecessor in graph[node]:
            cycle = visit(predecessor)
            if cycle:
                return cycle
        path.pop()
        visiting.remove(node)
        visited.add(node)
        return []

    for task in graph:
        cycle = visit(task)
        if cycle:
            return cycle
    return []


def _worker_matches(worker: Worker, task: Task) -> bool:
    required_skills = {task.required_skill.casefold(), *(value.casefold() for value in task.required_skills)}
    required_skills.discard("")
    if not required_skills:
        return False
    worker_skills = {value.casefold() for value in worker.all_skills}
    certifications = {value.casefold() for value in worker.certifications}
    return required_skills <= worker_skills and {value.casefold() for value in task.required_certifications} <= certifications


def _machine_matches(machine: Machine, task: Task) -> bool:
    if not task.machine_type:
        return False
    capabilities = {machine.machine_type.casefold(), *(value.casefold() for value in machine.capabilities)}
    return machine.machine_type.casefold() == task.machine_type.casefold() and {value.casefold() for value in task.machine_requirements} <= capabilities


def _vehicle_matches(vehicle: Vehicle, task: Task) -> bool:
    if not task.vehicle_type:
        return False
    capabilities = {vehicle.vehicle_type.casefold(), *(value.casefold() for value in vehicle.capabilities)}
    return vehicle.vehicle_type.casefold() == task.vehicle_type.casefold() and {value.casefold() for value in task.vehicle_requirements} <= capabilities


def _constrain_to_calendar(
    model: cp_model.CpModel,
    start: cp_model.IntVar,
    end: cp_model.IntVar,
    assigned: cp_model.IntVar,
    windows,
    horizon: int,
    name: str,
) -> None:
    applicable = [window for window in windows if window.start_minute < horizon and window.end_minute > 0]
    if not applicable:
        return
    choices = []
    for number, window in enumerate(applicable):
        choice = model.new_bool_var(f"{name}_{number}")
        model.add(choice <= assigned)
        model.add(start >= max(0, window.start_minute)).only_enforce_if(choice)
        model.add(end <= min(horizon, window.end_minute)).only_enforce_if(choice)
        choices.append(choice)
    model.add(sum(choices) == assigned)
