"""HTTP checks use a temporary workspace and never write into the real register."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import server
from careeros import research, sot, tracker


class LocalWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.previous = (tracker.DATA, sot.ROOT, sot.SOT, research.RESEARCH)
        for name in ("data", "sot", "web", "outputs", "exports", "research"):
            (self.root / name).mkdir()
        master = {"profile": {"name": "Test User", "city": "London"}, "roles": [],
                  "education": [], "skills": []}
        (self.root / "sot/master.yaml").write_text(yaml.safe_dump(master))
        (self.root / "sot/personal_context.yaml").write_text(yaml.safe_dump({"summaries": [], "positioning": "Test"}))
        (self.root / "web/index.html").write_text("<!doctype html><title>Test workspace</title>")
        self.httpd = server.create_server(self.root, 0)
        self.port = self.httpd.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        for name in tracker.TABLES:
            tracker.write(name, [])

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        tracker.DATA, sot.ROOT, sot.SOT, research.RESEARCH = self.previous
        self.temp.cleanup()

    def request(self, path, payload=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        body = None if payload is None else json.dumps(payload)
        hdr = {"Host": f"127.0.0.1:{self.port}"}
        if payload is not None:
            hdr.update({"Origin": self.origin, "Content-Type": "application/json",
                        "X-CareerOS-Token": self.httpd.workspace.token})
        hdr.update(headers or {})
        connection.request("GET" if payload is None else "POST", path, body=body, headers=hdr)
        response = connection.getresponse()
        status, out, response_headers = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return status, out, response_headers

    def post(self, route, payload):
        status, out, _ = self.request("/api/" + route, payload)
        return status, json.loads(out)

    def test_state_has_real_counts_and_no_source_verification_claim(self):
        tracker.add_row("targets", ["Organisation"], Organisation="Real target")
        status, raw, headers = self.request("/api/state")
        state = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertEqual(state["stats"]["roles_logged"], 0)
        self.assertEqual(len(state["tables"]["targets"]), 1)
        self.assertIn("Senior Executive", state["goal"])
        self.assertIn("not independent verification", state["evidence_note"])
        self.assertIn("have not been merged", state["history_notice"])
        self.assertEqual(state["token"], self.httpd.workspace.token)
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_application_save_deduplicates_then_records_dated_status(self):
        status, result = self.post("applications", {"Company": "Evidence Ltd", "Role": "Senior Executive", "Status": "shortlisted"})
        self.assertEqual(status, 200, result)
        ident = result["id"]
        self.post("applications", {"Company": "Evidence Ltd", "Role": "Senior Executive", "Notes": "Correction retained in audit"})
        self.assertEqual(len(tracker.read("applications")), 1)
        status, result = self.post("status", {"id": ident, "status": "applied", "on": "2026-10-01"})
        self.assertEqual(status, 200, result)
        self.assertEqual(tracker.read("applications")[0]["Date Applied"], "2026-10-01")

    def test_dated_outreach_is_a_record_and_future_dates_are_rejected(self):
        status, result = self.post("network", {"Name": "Known Person", "Company": "Evidence Ltd"})
        self.assertEqual(status, 200, result)
        status, result = self.post("outreach", {"id": result["id"], "event_date": "2026-10-01", "sent": "CV version one", "channel": "Email"})
        self.assertEqual(status, 200, result)
        self.assertIn("No message has been sent", result["message"])
        self.assertIn("2026-10-01: CV version one", tracker.read("network")[0]["Assets Sent"])
        status, _ = self.post("outreach", {"id": "N001", "event_date": "2999-01-01", "sent": "Future"})
        self.assertEqual(status, 400)

    def test_cross_origin_wrong_host_missing_origin_and_token_are_blocked(self):
        payload = {"Company": "Unwanted", "Role": "Role"}
        cases = [{"Origin": "https://attacker.example"}, {"Host": f"attacker.example:{self.port}"},
                 {"X-CareerOS-Token": "invalid"}, {"Origin": ""}]
        for headers in cases:
            with self.subTest(headers=headers):
                status, _, _ = self.request("/api/applications", payload, headers)
                self.assertEqual(status, 403)
        self.assertEqual(tracker.read("applications"), [])

    def test_no_arbitrary_paths_or_download_symlinks(self):
        (self.root / "outputs/review.md").write_text("Review this draft")
        (self.root / "secret.txt").write_text("private")
        (self.root / "outputs/escape.txt").symlink_to(self.root / "secret.txt")
        for path in ("/download/outputs/../secret.txt", "/download/outputs/%2e%2e/secret.txt",
                     "/download/sot/master.yaml", "/download/outputs/escape.txt", "/sot/master.yaml", "/server.py"):
            with self.subTest(path=path):
                status, _, _ = self.request(path)
                self.assertEqual(status, 404)
        status, raw, headers = self.request("/download/outputs/review.md")
        self.assertEqual(status, 200)
        self.assertEqual(raw, b"Review this draft")
        self.assertIn("attachment", headers["Content-Disposition"])

    def test_invalid_fields_and_unknown_actions_do_not_write(self):
        status, _ = self.post("applications", {"Company": "A", "Role": "B", "Shell command": "bad"})
        self.assertEqual(status, 400)
        status, _ = self.post("run", {"command": "anything"})
        self.assertEqual(status, 404)
        self.assertEqual(tracker.read("applications"), [])

    def test_jd_is_saved_before_fixed_drafting_command(self):
        _, app = self.post("applications", {"Company": "A", "Role": "Senior Executive", "Status": "shortlisted"})
        def check_command(args):
            self.assertEqual(args[0], "tailor")
            path = Path(args[1])
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_text(), "Real supplied JD text")
            self.assertIn("--company=A", args)
            return "Draft created"
        with patch.object(self.httpd.workspace, "command", side_effect=check_command):
            status, result = self.post("draft", {"id": app["id"], "jd_text": "Real supplied JD text"})
        self.assertEqual(status, 200, result)
        self.assertEqual(len(list((self.root / "jobs").glob("*.txt"))), 1)


if __name__ == "__main__":
    unittest.main()
