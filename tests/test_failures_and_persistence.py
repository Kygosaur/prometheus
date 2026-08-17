import tempfile
import unittest
from pathlib import Path

from planning_agent.database import PlanningDatabase
from planning_agent.llm import understand_request
from planning_agent.local_llm import LocalLLM
from planning_agent.rag import WorkspaceIndex
from planning_agent.security import hash_password, verify_password


class FakeMalformedModel:
    def chat(self, *args, **kwargs):
        return "this is not JSON"


class FailureAndPersistenceTests(unittest.TestCase):
    def test_rag_empty_results_and_unsupported_document(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "binary.exe").write_bytes(b"ignored")
            index = WorkspaceIndex(root, enable_semantic=False)
            self.assertEqual(index.build(), 0)
            self.assertEqual(index.search("anything"), [])

    def test_llm_malformed_json(self):
        with self.assertRaisesRegex(ValueError, "valid planning-constraint JSON"):
            understand_request(FakeMalformedModel(), "plan")

    def test_llm_unreachable(self):
        client = LocalLLM("http://127.0.0.1:9/v1", "missing", timeout_seconds=1)
        with self.assertRaisesRegex(RuntimeError, "Cannot reach the local LLM"):
            client.chat([{"role": "user", "content": "hello"}])

    def test_schedule_history_and_approval_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            database = PlanningDatabase(Path(directory) / "planning.db")
            identifier = database.create_schedule("plan", {"scheduled": []}, "planner")
            self.assertEqual(database.list_schedules()[0]["status"], "draft")
            database.review_schedule(identifier, "approved", "supervisor", "checked")
            self.assertEqual(database.list_schedules()[0]["status"], "approved")
            with self.assertRaises(KeyError):
                database.review_schedule(identifier, "rejected", "supervisor")

    def test_password_hashing(self):
        encoded = hash_password("a-secure-password")
        self.assertTrue(verify_password("a-secure-password", encoded))
        self.assertFalse(verify_password("wrong-password", encoded))


if __name__ == "__main__":
    unittest.main()
