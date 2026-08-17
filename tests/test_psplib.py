import tempfile
import unittest
from pathlib import Path

from planning_agent.psplib import parse_sm, serial_schedule


SAMPLE = """
PRECEDENCE RELATIONS:
jobnr. #modes #successors successors
1 1 2 2 3
2 1 1 4
3 1 1 4
4 1 0
REQUESTS/DURATIONS:
jobnr. mode duration R 1 R 2
1 1 0 0 0
2 1 2 2 1
3 1 3 1 2
4 1 0 0 0
RESOURCEAVAILABILITIES:
R 1 R 2
2 2
"""


class PsplibTests(unittest.TestCase):
    def test_parse_and_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.sm"
            path.write_text(SAMPLE, encoding="utf-8")
            instance = parse_sm(path)
        self.assertEqual(instance.capacities, (2, 2))
        schedule = serial_schedule(instance)
        self.assertGreaterEqual(schedule[4][0], schedule[2][1])
        self.assertGreaterEqual(schedule[4][0], schedule[3][1])


if __name__ == "__main__":
    unittest.main()
