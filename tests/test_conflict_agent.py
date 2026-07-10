import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from conflict_agent import build_conflict_report, interpret_conflict


class ConflictAgentTests(unittest.TestCase):
    def test_interpret_conflict_marks_origin_conflicts_as_high(self):
        conflict = {
            "flight_a": "flight_a",
            "flight_b": "flight_b",
            "volume_a_index": 0,
            "volume_b_index": 1,
            "volume_a_type": "origin",
            "volume_b_type": "segment",
            "alt_a_ft": "0–300",
            "alt_b_ft": "280–320",
            "time_a_utc": "10:00:00–10:02:00",
            "time_b_utc": "10:01:00–10:03:00",
        }

        summary = interpret_conflict(conflict)

        self.assertEqual(summary["severity"], "high")
        self.assertIn("origin", summary["summary"].lower())
        self.assertIn("recommendation", summary)

    def test_build_conflict_report_contains_conflict_count_and_summary(self):
        summaries = [
            interpret_conflict(
                {
                    "flight_a": "alpha",
                    "flight_b": "beta",
                    "volume_a_index": 2,
                    "volume_b_index": 4,
                    "volume_a_type": "segment",
                    "volume_b_type": "segment",
                    "alt_a_ft": "250–300",
                    "alt_b_ft": "250–300",
                    "time_a_utc": "10:00:00–10:02:00",
                    "time_b_utc": "10:01:00–10:03:00",
                }
            )
        ]

        report = build_conflict_report(summaries, generated_at="2026-07-10T18:15:33Z")

        self.assertIn("1 conflict", report)
        self.assertIn("alpha", report)
        self.assertIn("beta", report)
        self.assertIn("medium", report.lower())


if __name__ == "__main__":
    unittest.main()
