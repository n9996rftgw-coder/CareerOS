import csv
import json
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from careeros import tracker


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.patch = patch.object(tracker, "DATA", self.path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def incoming(self, rows):
        p = self.path / "incoming.csv"
        with p.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)
        return p

    def test_duplicate_updates_same_id_without_reset(self):
        rid, created = tracker.upsert_application(Company="Example Sport", Role="Content Manager", Notes="original")
        tracker.set_status(rid, "applied")
        other, created = tracker.upsert_application(Company="example sport", Role="Content Manager", Lane="Content & Social")
        self.assertEqual(rid, other)
        self.assertFalse(created)
        self.assertEqual(tracker.read("applications")[0]["Status"], "applied")

    def test_import_blanks_do_not_erase(self):
        rid, _ = tracker.upsert_application(Company="Example", Role="Manager", Notes="keep")
        tracker.set_status(rid, "applied")
        tracker.safe_import("applications", self.incoming([{"ID": rid, "Status": "", "Date Applied": "", "Notes": ""}]))
        row = tracker.read("applications")[0]
        self.assertEqual(row["Notes"], "keep")
        self.assertEqual(row["Status"], "applied")
        self.assertTrue(row["Date Applied"])

    def test_bad_import_is_atomic(self):
        rid, _ = tracker.upsert_application(Company="Example", Role="Manager")
        before = (self.path / "applications.csv").read_bytes()
        with self.assertRaises(ValueError):
            tracker.safe_import("applications", self.incoming([{"ID": rid, "Status": "applied"}, {"ID": "bad", "Status": "nonsense"}]))
        self.assertEqual(before, (self.path / "applications.csv").read_bytes())

    def test_duplicate_business_key_import_rejected(self):
        tracker.upsert_application(Company="Example", Role="Manager")
        with self.assertRaises(ValueError):
            tracker.safe_import("applications", self.incoming([{"ID": "A002", "Company": "Example", "Role": "Manager"}]))

    def test_interview_history_survives_rejection(self):
        rid, _ = tracker.upsert_application(Company="Example", Role="Manager")
        when = (tracker.current_date() - timedelta(days=20)).isoformat()
        tracker.set_status(rid, "applied", on=when)
        tracker.set_status(rid, "interview_1")
        tracker.set_status(rid, "rejected")
        row = tracker.read("applications")[0]
        self.assertTrue(row["First Interview Date"])
        self.assertEqual(tracker.stats()["interview_rate_pct"], 100)
        self.assertEqual(tracker.stats()["response_rate_pct"], 100)

    def test_no_submission_inferred_from_rejected(self):
        rid, _ = tracker.upsert_application(Company="Example", Role="Manager")
        tracker.set_status(rid, "rejected")
        self.assertEqual(tracker.stats()["sent"], 0)

    def test_dates_and_choices_checked(self):
        with self.assertRaises(ValueError):
            tracker.upsert_application(Company="Example", Role="Manager", Deadline="tomorrow")
        with self.assertRaises(ValueError):
            tracker.add_row("network", ["Name", "Company"], Name="Test", Company="Example", Status="wrong")

    def test_journal_preserves_corrections(self):
        rid, _ = tracker.upsert_application(Company="Example", Role="Manager", Notes="first version")
        tracker.upsert_application(Company="Example", Role="Manager", Notes="corrected version")
        events = [json.loads(x) for x in (self.path / "events.jsonl").read_text().splitlines()]
        self.assertTrue(any(e["rows"] and e["rows"][0]["Notes"] == "first version" for e in events))
        self.assertTrue(any(e["rows"] and e["rows"][0]["Notes"] == "corrected version" for e in events))

    def test_next_id_uses_max(self):
        tracker.write("targets", [{"ID": "T001", "Organisation": "First"}, {"ID": "T009", "Organisation": "Ninth"}])
        rid, _ = tracker.add_row("targets", ["Organisation"], Organisation="New")
        self.assertEqual(rid, "T010")

    def test_concurrent_writers_keep_all_rows(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda n: tracker.upsert_application(Company="Example", Role="Role " + str(n)), range(10)))
        self.assertEqual(len(tracker.read("applications")), 10)
        self.assertEqual(len({r["ID"] for r in tracker.read("applications")}), 10)

    def test_blank_followups_not_due(self):
        tracker.upsert_application(Company="Example", Role="Manager")
        self.assertEqual(tracker.today_list(), [])

    def test_no_observations_means_no_rate(self):
        stats = tracker.stats()
        self.assertIsNone(stats["response_rate_pct"])
        self.assertIsNone(stats["interview_rate_pct"])
        self.assertIsNone(stats["outreach_reply_rate_pct"])

    def test_bad_reference_does_not_commit(self):
        with self.assertRaises(ValueError):
            tracker.upsert_application(Company="Example", Role="Manager", **{"Target ID": "T999"})
        self.assertEqual(tracker.read("applications"), [])


if __name__ == "__main__":
    unittest.main()
