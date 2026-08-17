import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from planning_agent.api import ChatRequest, _event_stream, state
from planning_agent.database import PlanningDatabase
from planning_agent.intent import IntentDecision, route_request
from planning_agent.models import PlanningRequest, ScheduledTask, ScheduleResult
from planning_agent.rag import Passage
from planning_agent.responses import compose_response
from planning_agent.security import Principal


class FakeModel:
    def __init__(self, response):
        self.response = response

    def chat(self, *_args, **_kwargs):
        return self.response


class IntentAndResponseTests(unittest.TestCase):
    def test_router_supports_rag_and_planning_together(self):
        decision = route_request(FakeModel('{"general":false,"rag":true,"planning":true}'), "schedule welding using the SOP")
        self.assertFalse(decision.general)
        self.assertTrue(decision.rag)
        self.assertTrue(decision.planning)

    def test_router_handles_malformed_json_with_conservative_fallback(self):
        decision = route_request(FakeModel("not json"), "Schedule welding according to the PPE SOP")
        self.assertTrue(decision.planning)
        self.assertTrue(decision.rag)
        self.assertEqual(decision.method, "rule-fallback")

    def test_composer_contains_structured_schedule_metadata(self):
        task = ScheduledTask("A", 8, 10, ("W3",), "M2", None, "high", 12, True, "optimized")
        result = ScheduleResult((task,), (), 2, {"workers": (), "machines": (), "vehicles": ()}, {"status": "OPTIMAL"})
        passage = Passage("Wear face protection", "Welding_SOP.pdf", "page 14", 0.9)
        response = compose_response(
            "Schedule created", route_request(FakeModel('{"general":false,"rag":true,"planning":true}'), "plan"),
            [passage], {"solver_seconds": 0.2}, result, "draft-1",
        )
        self.assertEqual(response["schedule"]["solver_status"], "OPTIMAL")
        self.assertEqual(response["schedule"]["approval_status"], "draft")
        self.assertEqual(response["sources"][0]["location"], "page 14")
        self.assertEqual(response["timing"]["total_seconds"], 0.2)


class ParallelPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_rag_constraints_and_workbook_load_run_concurrently(self):
        def delayed(value):
            time.sleep(0.15)
            return value

        class SlowIndex:
            def search(self, *_args):
                return delayed([Passage("PPE evidence", "SOP.pdf", "page 1", 0.9)])

        with tempfile.TemporaryDirectory() as directory:
            workbook = Path(directory) / "planning.xlsx"
            workbook.touch()
            old_workbook = os.environ.get("PLANNING_WORKBOOK")
            os.environ["PLANNING_WORKBOOK"] = str(workbook)
            state.index = SlowIndex()
            state.client = FakeModel("unused")
            state.database = PlanningDatabase(Path(directory) / "history.db")
            empty_result = ScheduleResult((), (), 0, {"workers": (), "machines": (), "vehicles": ()}, {"status": "OPTIMAL"})
            try:
                with (
                    patch("planning_agent.api.route_request", return_value=IntentDecision(rag=True, planning=True)),
                    patch("planning_agent.api.understand_request", side_effect=lambda *_: delayed(PlanningRequest())),
                    patch("planning_agent.api.load_workbook", side_effect=lambda *_: delayed(([], [], [], []))),
                    patch("planning_agent.api.create_schedule", return_value=empty_result),
                    patch("planning_agent.api.explain_schedule", return_value="Draft ready"),
                ):
                    events = [event async for event in _event_stream(ChatRequest(question="Schedule using the SOP"), Principal("planner", "planner"))]
                complete = next(event for event in events if event.startswith("event: complete"))
                payload = json.loads(complete.split("data: ", 1)[1])
                timing = payload["timing"]
                sequential = timing["retrieval_seconds"] + timing["constraint_parser_seconds"] + timing["workbook_load_seconds"]
                self.assertLess(timing["parallel_preparation_seconds"], sequential - 0.15)
            finally:
                if old_workbook is None:
                    os.environ.pop("PLANNING_WORKBOOK", None)
                else:
                    os.environ["PLANNING_WORKBOOK"] = old_workbook


if __name__ == "__main__":
    unittest.main()
