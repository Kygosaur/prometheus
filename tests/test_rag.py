import tempfile
import unittest
from pathlib import Path

from planning_agent.rag import WorkspaceIndex


class WorkspaceIndexTests(unittest.TestCase):
    def test_search_is_local_and_excludes_env_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manual.txt").write_text("Welding requires a face shield and gloves.", encoding="utf-8")
            (root / ".env").write_text("SECRET_TOKEN=do-not-index", encoding="utf-8")
            index = WorkspaceIndex(root)
            self.assertEqual(index.build(), 1)
            results = index.search("What does welding require?")
            self.assertEqual(results[0].document, "manual.txt")
            self.assertEqual(index.search("do-not-index"), [])

    def test_inverted_index_returns_best_matching_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "machines.txt").write_text("CNC machine maintenance schedule", encoding="utf-8")
            (root / "workers.txt").write_text("welding worker skills and shifts", encoding="utf-8")
            index = WorkspaceIndex(root)
            index.build()
            self.assertEqual(index.search("CNC maintenance")[0].document, "machines.txt")

    def test_editable_terminology_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "safety.txt").write_text("Protective headgear is mandatory personal protective equipment.", encoding="utf-8")
            index = WorkspaceIndex(root, enable_semantic=False)
            index.build()
            self.assertEqual(index.search("Is a helmet PPE?")[0].document, "safety.txt")


if __name__ == "__main__":
    unittest.main()
