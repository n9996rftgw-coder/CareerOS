"""Formula-engine regression fixtures. No production CSVs or workbook are changed."""
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkbookFormulaTests(unittest.TestCase):
    def test_submission_history_dates_ids_and_recalculation(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "build_sheet.py"), str(ROOT), str(ROOT / "exports/CareerOS_Tracker.xlsx"), "--test-only"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Workbook fixtures passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
