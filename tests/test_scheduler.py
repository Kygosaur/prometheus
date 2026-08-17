import unittest

from planning_agent.models import Machine, PlanningRequest, Task, Worker
from planning_agent.scheduler import create_schedule


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.workers = [Worker("W1", "weld"), Worker("W2", "weld")]
        self.machines = [Machine("M1", "welder")]

    def test_resources_do_not_overlap(self):
        tasks = [
            Task("A", 2, "high", None, "weld", 1, "welder"),
            Task("B", 3, "medium", None, "weld", 1, "welder"),
        ]
        result = create_schedule(self.workers, tasks, self.machines)
        self.assertEqual(len(result.scheduled), 2)
        self.assertEqual(result.scheduled[0].end_hour, result.scheduled[1].start_hour)
        self.assertEqual(result.makespan_hours, 5)

    def test_blocked_machine_is_reported(self):
        task = Task("A", 2, "high", None, "weld", 1, "welder")
        result = create_schedule(self.workers, [task], self.machines, request=PlanningRequest(blocked_machines=("M1",)))
        self.assertEqual(len(result.scheduled), 0)
        self.assertEqual(result.unscheduled[0].reason, "No available compatible machine")
        self.assertEqual(result.unavailable_resources["machines"], ("M1",))

    def test_precedence_is_respected(self):
        tasks = [
            Task("A", 2, "low", None, "weld", 1, "welder"),
            Task("B", 1, "critical", None, "weld", 1, "welder", ("A",)),
        ]
        result = create_schedule(self.workers, tasks, self.machines)
        by_name = {task.task: task for task in result.scheduled}
        self.assertGreaterEqual(by_name["B"].start_hour, by_name["A"].end_hour)

    def test_unscheduled_predecessor_propagates(self):
        tasks = [
            Task("A", 2, "high", None, "paint", 1, "welder"),
            Task("B", 1, "high", None, "weld", 1, "welder", ("A",)),
        ]
        result = create_schedule(self.workers, tasks, self.machines)
        self.assertEqual({x.task for x in result.unscheduled}, {"A", "B"})


if __name__ == "__main__":
    unittest.main()

