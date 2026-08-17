import tempfile
import unittest
from pathlib import Path

import pandas as pd

from planning_agent.calendars import parse_calendar
from planning_agent.data import load_workbook


class DataValidationTests(unittest.TestCase):
    def test_unknown_dependency(self):
        with self.assertRaisesRegex(ValueError, "unknown predecessors"):
            self._load(tasks=[self._task(Predecessors="Missing")])

    def test_duplicate_names_case_insensitive(self):
        with self.assertRaisesRegex(ValueError, "Duplicate worker"):
            self._load(workers=[self._worker("Alice"), self._worker("alice")])

    def test_invalid_duration(self):
        with self.assertRaisesRegex(ValueError, "Invalid duration"):
            self._load(tasks=[self._task(Duration_Hours=0)])

    def test_missing_worker_skill(self):
        worker = {"Worker": "Alice", "Available": True, "Skill": ""}
        with self.assertRaisesRegex(ValueError, "at least one skill"):
            self._load(workers=[worker])

    def test_calendar_formats(self):
        availability, _ = parse_calendar("Mon: 08:00–17:00\nTue: 08:00–17:00\nWed: leave")
        self.assertEqual(len(availability), 2)
        overnight, _ = parse_calendar("Shift: 20:00–08:00")
        self.assertEqual(len(overnight), 7)
        _, maintenance = parse_calendar("Mon: 24h\nTue: maintenance 10:00–14:00")
        self.assertEqual(len(maintenance), 1)

    def _load(self, workers=None, tasks=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "planning.xlsx"
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                pd.DataFrame(workers or [self._worker("Alice")]).to_excel(writer, sheet_name="Workers", index=False)
                pd.DataFrame(tasks or [self._task()]).to_excel(writer, sheet_name="Tasks", index=False)
                pd.DataFrame([{"Machine": "M1", "Type": "welder", "Available": True}]).to_excel(writer, sheet_name="Machines", index=False)
            return load_workbook(path)

    @staticmethod
    def _worker(name):
        return {"Worker": name, "Skill": "weld", "Available": True}

    @staticmethod
    def _task(**updates):
        row = {"Task": "T1", "Duration_Hours": 2, "Priority": "high", "Deadline_Days": 1, "Required_Skill": "weld", "Workers_Needed": 1, "Machine_Type": "welder", "Predecessors": ""}
        row.update(updates)
        return row


if __name__ == "__main__":
    unittest.main()
