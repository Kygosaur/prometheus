from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RcpspJob:
    job: int
    duration: int
    demands: tuple[int, ...]
    successors: tuple[int, ...]


@dataclass(frozen=True)
class RcpspInstance:
    capacities: tuple[int, ...]
    jobs: tuple[RcpspJob, ...]


def parse_sm(path: str | Path) -> RcpspInstance:
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    precedence_start = _find(lines, "PRECEDENCE RELATIONS")
    requests_start = _find(lines, "REQUESTS/DURATIONS")
    capacities_start = _find(lines, "RESOURCEAVAILABILITIES")
    successors: dict[int, tuple[int, ...]] = {}
    for line in lines[precedence_start + 1:requests_start]:
        values = _ints(line)
        if len(values) >= 3:
            successors[values[0]] = tuple(values[3:3 + values[2]])
    jobs: list[RcpspJob] = []
    for line in lines[requests_start + 1:capacities_start]:
        values = _ints(line)
        if len(values) >= 4:
            job, mode, duration, *demands = values
            if mode == 1:
                jobs.append(RcpspJob(job, duration, tuple(demands), successors.get(job, ())))
    resource_count = len(jobs[0].demands) if jobs else 0
    capacity_candidates: list[list[int]] = []
    for line in lines[capacities_start + 1:]:
        values = _ints(line)
        if resource_count and len(values) >= resource_count:
            capacity_candidates.append(values)
    if not jobs or not capacity_candidates:
        raise ValueError("Could not parse jobs or resource capacities from PSPLIB instance")
    # Resource-label headers often contain digits ("R 1 R 2 ..."). The actual
    # capacity row is the final numeric row in the section.
    capacity_values = capacity_candidates[-1]
    return RcpspInstance(tuple(capacity_values[-resource_count:]), tuple(jobs))


def serial_schedule(instance: RcpspInstance) -> dict[int, tuple[int, int]]:
    jobs = {j.job: j for j in instance.jobs}
    predecessors = {job: set() for job in jobs}
    for job in jobs.values():
        for successor in job.successors:
            if successor in predecessors:
                predecessors[successor].add(job.job)
    schedule: dict[int, tuple[int, int]] = {}
    usage: list[list[int]] = []
    while len(schedule) < len(jobs):
        ready = sorted(j for j in jobs if j not in schedule and predecessors[j] <= schedule.keys())
        if not ready:
            raise ValueError("Instance contains a precedence cycle")
        job = jobs[ready[0]]
        earliest = max((schedule[p][1] for p in predecessors[job.job]), default=0)
        start = earliest
        while not _fits(usage, start, job.duration, job.demands, instance.capacities):
            start += 1
        end = start + job.duration
        while len(usage) < end:
            usage.append([0] * len(instance.capacities))
        for time in range(start, end):
            for resource, demand in enumerate(job.demands):
                usage[time][resource] += demand
        schedule[job.job] = (start, end)
    return schedule


def _fits(usage: list[list[int]], start: int, duration: int, demands: tuple[int, ...], capacities: tuple[int, ...]) -> bool:
    if any(d > c for d, c in zip(demands, capacities)):
        raise ValueError("A job demand exceeds total resource capacity")
    for time in range(start, start + duration):
        current = usage[time] if time < len(usage) else [0] * len(capacities)
        if any(current[r] + demands[r] > capacities[r] for r in range(len(capacities))):
            return False
    return True


def _find(lines: list[str], marker: str) -> int:
    try:
        return next(i for i, line in enumerate(lines) if marker in line.upper())
    except StopIteration as error:
        raise ValueError(f"Missing PSPLIB section: {marker}") from error


def _ints(line: str) -> list[int]:
    return [int(x) for x in re.findall(r"-?\d+", line)]
