import unittest

from planning_agent.calendars import DAY_MINUTES, parse_calendar
from planning_agent.models import Machine, PlanningRequest, Task, TimeWindow, Vehicle, Worker
from planning_agent.scheduler import create_schedule


def task(name="T", duration=2, priority="medium", deadline=None, skill="weld", workers=1, machine="welder", predecessors=(), vehicle=None, **kwargs):
    return Task(name, duration, priority, deadline, skill, workers, machine, predecessors, vehicle, **kwargs)


class ProductionSchedulerTests(unittest.TestCase):
    def test_worker_conflict(self):
        result = create_schedule([Worker("A", "weld")], [task("T1"), task("T2")], [Machine("M1", "welder"), Machine("M2", "welder")])
        self.assertFalse(_overlap(result.scheduled[0], result.scheduled[1]))

    def test_machine_conflict(self):
        result = create_schedule([Worker("A", "weld"), Worker("B", "weld")], [task("T1"), task("T2")], [Machine("M", "welder")])
        self.assertFalse(_overlap(result.scheduled[0], result.scheduled[1]))

    def test_vehicle_conflict(self):
        resources = [Vehicle("V", "forklift")]
        result = create_schedule([Worker("A", "weld"), Worker("B", "weld")], [task("T1", vehicle="forklift"), task("T2", vehicle="forklift")], [Machine("M1", "welder"), Machine("M2", "welder")], resources)
        self.assertFalse(_overlap(result.scheduled[0], result.scheduled[1]))

    def test_multiple_workers_per_task(self):
        result = create_schedule([Worker("A", "weld"), Worker("B", "weld")], [task(workers=2)], [Machine("M", "welder")])
        self.assertEqual(result.scheduled[0].workers, ("A", "B"))

    def test_multiple_machine_and_vehicle_candidates(self):
        result = create_schedule([Worker("A", "weld")], [task(vehicle="forklift")], [Machine("M1", "welder"), Machine("M2", "welder")], [Vehicle("V1", "forklift"), Vehicle("V2", "forklift")])
        self.assertIn(result.scheduled[0].machine, {"M1", "M2"})
        self.assertIn(result.scheduled[0].vehicle, {"V1", "V2"})

    def test_priority_ordering(self):
        result = create_schedule([Worker("A", "weld")], [task("Low", priority="low"), task("Critical", priority="critical")], [Machine("M", "welder")])
        by_name = {item.task: item for item in result.scheduled}
        self.assertLess(by_name["Critical"].start_hour, by_name["Low"].start_hour)

    def test_deadline_success_and_violation(self):
        result = create_schedule([Worker("A", "weld")], [task("Success", duration=1, deadline=2), task("Late", duration=3, deadline=1)], [Machine("M", "welder")])
        by_name = {item.task: item for item in result.scheduled}
        self.assertTrue(by_name["Success"].deadline_met)
        self.assertFalse(by_name["Late"].deadline_met)

    def test_blocked_worker_and_vehicle(self):
        request = PlanningRequest(blocked_workers=("a",), blocked_vehicles=("v",))
        result = create_schedule([Worker("A", "weld")], [task(vehicle="forklift")], [Machine("M", "welder")], [Vehicle("V", "forklift")], request)
        self.assertEqual(len(result.scheduled), 0)
        self.assertIn("A", result.unavailable_resources["workers"])
        self.assertIn("V", result.unavailable_resources["vehicles"])

    def test_precedence_chain_and_diamond(self):
        tasks = [task("A"), task("B", predecessors=("A",)), task("C", predecessors=("A",)), task("D", predecessors=("B", "C"))]
        result = create_schedule([Worker("W1", "weld"), Worker("W2", "weld")], tasks, [Machine("M1", "welder"), Machine("M2", "welder")])
        by_name = {item.task: item for item in result.scheduled}
        self.assertGreaterEqual(by_name["D"].start_hour, max(by_name["B"].end_hour, by_name["C"].end_hour))

    def test_circular_dependency(self):
        result = create_schedule([Worker("A", "weld")], [task("A", predecessors=("B",)), task("B", predecessors=("A",))], [Machine("M", "welder")])
        self.assertEqual(len(result.scheduled), 0)
        self.assertTrue(all(item.reason == "Precedence cycle" for item in result.unscheduled))

    def test_missing_skill_machine_and_unavailable_resource(self):
        result = create_schedule([Worker("A", "paint", available=False)], [task()], [Machine("M", "cutter", available=False)])
        self.assertEqual(len(result.scheduled), 0)
        self.assertEqual(result.unscheduled[0].reason, "Insufficient available skilled workers")

    def test_multiple_simultaneous_tasks(self):
        result = create_schedule([Worker("A", "weld"), Worker("B", "weld")], [task("T1"), task("T2")], [Machine("M1", "welder"), Machine("M2", "welder")])
        self.assertEqual({item.start_hour for item in result.scheduled}, {0.0})

    def test_case_insensitive_multi_skill_and_certification(self):
        worker = Worker("A", "Paint", skills=("WELD",), certifications=("HOT-WORK",))
        requested = task(required_skills=("weld",), required_certifications=("hot-work",))
        self.assertEqual(len(create_schedule([worker], [requested], [Machine("M", "welder")]).scheduled), 1)

    def test_no_vehicle_required(self):
        self.assertIsNone(create_schedule([Worker("A", "weld")], [task()], [Machine("M", "welder")]).scheduled[0].vehicle)

    def test_setup_and_travel_are_included(self):
        requested = task(duration=2, setup_hours=1, travel_hours=0.5)
        result = create_schedule([Worker("A", "weld")], [requested], [Machine("M", "welder")])
        self.assertEqual(result.makespan_hours, 3.5)
        self.assertEqual(result.scheduled[0].work_duration_hours, 2)

    def test_worker_shift_and_machine_maintenance(self):
        worker_windows, _ = parse_calendar("Mon: 08:00-18:00")
        machine_windows, maintenance = parse_calendar("Mon: 24h; Mon: maintenance 10:00-14:00")
        worker = Worker("A", "weld", availability=worker_windows)
        machine = Machine("M", "welder", availability=machine_windows, maintenance=maintenance)
        result = create_schedule([worker], [task(duration=4)], [machine])
        self.assertEqual(result.scheduled[0].start_time, "Mon 14:00")

    def test_overnight_shift(self):
        windows, _ = parse_calendar("Shift: 20:00-08:00")
        worker = Worker("Night", "weld", availability=windows)
        result = create_schedule([worker], [task(duration=4)], [Machine("M", "welder")])
        self.assertEqual(result.scheduled[0].start_time, "Mon 20:00")


def _overlap(left, right):
    return left.start_hour < right.end_hour and right.start_hour < left.end_hour


if __name__ == "__main__":
    unittest.main()
