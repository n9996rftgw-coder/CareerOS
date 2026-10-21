"""Regression checks for evidence, readiness, and immutable output history.

Fixtures contain invented test records only. No live source or application is changed.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cli
from careeros import builder, jd, reviewer, sot


def fixture():
    master = {
        "profile": {"name": "Test Candidate", "city": "London", "email": "test@example.invalid", "portfolio": ""},
        "roles": [{"id": "r1", "employer": "Test Organisation", "title": "Marketing Executive", "location": "London",
                   "start": "Jan 2024", "end": "Dec 2024", "bullets": [
                       {"id": "r1-01", "text": "Created videos for a campaign.", "status": "confirmed", "tags": ["budget"]}]}],
        "skills": ["Video Editing"],
        "education": [{"institution": "Test University", "award": "MSc Marketing", "start": "Sep 2023", "end": "Sep 2024"}],
        "certifications": [{"text": "Test certification"}], "awards": [{"text": "Test award"}],
    }
    context = {"summaries": [{"id": "content", "status": "confirmed", "text": "Marketing professional.",
                               "evidence": ["r1-01", "education.0.award", "profile.city"]}]}
    parsed = jd.parse("Video production", title="Senior Marketing Executive")
    return master, context, parsed, builder.build(master, context, parsed)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.master, self.context, self.parsed, self.cv = fixture()

    def report(self, **kw):
        return reviewer.review(self.cv, self.master, self.parsed, self.context, pages=kw.pop("pages", 1), **kw)

    def test_confirmed_traced_fixture_can_pass(self):
        report = self.report()
        self.assertTrue(report["ready"], report["checks"])

    def test_every_nonbullet_section_is_traced(self):
        changes = [
            lambda cv: cv["profile"].update(city="Invented city"),
            lambda cv: cv["roles"][0].update(employer="Invented employer"),
            lambda cv: cv["roles"][0].update(title="Invented title"),
            lambda cv: cv["roles"][0].update(location="Invented location"),
            lambda cv: cv["roles"][0].update(dates="Jan 2020 – Dec 2024"),
            lambda cv: cv["skills"].append("Invented skill"),
            lambda cv: cv["education"][0].update(award="Invented degree"),
            lambda cv: cv["certifications"].append("Invented certification"),
            lambda cv: cv["awards"].append("Invented award"),
            lambda cv: cv["summary"].update(text="Invented experience"),
            lambda cv: cv.update(target_title="Invented target"),
        ]
        for change in changes:
            with self.subTest(change=change):
                self.cv = fixture()[3]
                change(self.cv)
                self.assertFalse(self.report()["ready"])

    def test_summary_requires_real_context_and_evidence(self):
        self.assertFalse(reviewer.review(self.cv, self.master, self.parsed, pages=1)["ready"])
        for evidence in ([], ["missing-bullet"], ["education.99.award"], "r1-01"):
            with self.subTest(evidence=evidence):
                self.context["summaries"][0]["evidence"] = evidence
                self.assertFalse(self.report()["ready"])

    def test_drafts_flags_and_public_pending_block_ready(self):
        for field, value in (("status", "draft"), ("flag", "Unresolved ownership"), ("public", "pending")):
            for section in ("bullet", "role", "summary", "certification", "award", "education"):
                with self.subTest(field=field, section=section):
                    self.setUp()
                    source = {"bullet": self.master["roles"][0]["bullets"][0], "role": self.master["roles"][0],
                              "summary": self.context["summaries"][0], "certification": self.master["certifications"][0],
                              "award": self.master["awards"][0], "education": self.master["education"][0]}[section]
                    source[field] = value
                    self.cv = builder.build(self.master, self.context, self.parsed)
                    self.assertFalse(self.report()["ready"])

    def test_cross_role_bullet_attribution_is_rejected(self):
        another = copy.deepcopy(self.master["roles"][0])
        another["id"] = "r2"
        another["bullets"][0]["id"] = "r2-01"
        self.master["roles"].append(another)
        self.cv["roles"][0]["bullets"][0]["id"] = "r2-01"
        self.assertFalse(self.report()["ready"])

    def test_hidden_tags_are_not_printed_keyword_coverage(self):
        self.parsed = jd.parse("budget", title="Senior Marketing Executive")
        report = self.report()
        self.assertEqual(report["coverage_pct"], 0)
        self.assertEqual(report["gaps"], ["budget"])

    def test_keywords_use_word_boundaries(self):
        self.assertEqual(builder.score_text("production", [], [("pr", 1)])[0], 0)
        self.assertEqual(builder.score_text("commercial", [], [("crm", 1)])[0], 0)
        self.assertEqual(builder.score_text("PR campaign", [], [("pr", 1)])[0], 1)

    def test_unknown_or_excess_page_count_blocks_ready(self):
        for pages in (None, 0, True, 2):
            with self.subTest(pages=pages):
                self.assertFalse(self.report(pages=pages)["ready"])

    def test_duplicate_source_ids_fail_instead_of_overwriting_proof(self):
        self.master["roles"].append(copy.deepcopy(self.master["roles"][0]))
        failures = [message for level, message in sot.validate(self.master) if level == "FAIL"]
        self.assertTrue(any("duplicate role id" in message for message in failures))
        self.assertTrue(any("duplicate bullet id" in message for message in failures))
        self.assertFalse(self.report()["ready"])

    def test_reversed_dates_and_missing_schema_are_validation_failures(self):
        self.master["roles"][0]["start"] = "Jan 2025"
        self.assertTrue(any(level == "FAIL" and "after end" in message for level, message in sot.validate(self.master)))
        self.assertTrue(any(level == "FAIL" for level, _ in sot.validate({})))

    def test_summary_platform_claims_cannot_bypass_bullet_checks(self):
        for text in ("Drove 15B+ views.", "Drove 2.3B+ views within the team.", "Contributed within a campaign that generated 15B+ views."):
            with self.subTest(text=text):
                self.context["summaries"][0]["text"] = text
                self.cv["summary"]["text"] = text
                self.assertFalse(self.report()["ready"])
        text = "Contributed to channels that generated 15B+ views."
        self.context["summaries"][0]["text"] = text
        self.cv["summary"]["text"] = text
        self.assertTrue(self.report()["ready"])

    def test_same_day_outputs_get_unique_immutable_revisions(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(cli, "OUT", Path(temp)):
            version1, folder1 = cli.new_version_folder("20261021-test-company-content")
            (folder1 / "jd.txt").write_text("Original job description")
            version2, folder2 = cli.new_version_folder("20261021-test-company-content")
            self.assertNotEqual(version1, version2)
            self.assertNotEqual(folder1, folder2)
            self.assertEqual((folder1 / "jd.txt").read_text(), "Original job description")

    def test_output_filenames_are_stable_and_cannot_escape_folder(self):
        name = cli.document_name({"name": "../../ Candidate Name"}, "../ Company / role")
        self.assertEqual(name, cli.document_name({"name": "../../ Candidate Name"}, "../ Company / role"))
        self.assertNotIn("/", name)
        self.assertNotIn("..", name)
        self.assertTrue(name.endswith(".docx"))

    def test_node_configuration_supports_env_and_runtime_file(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(cli, "ROOT", Path(temp)), patch.dict(os.environ, {}, clear=True):
            (Path(temp) / ".runtime.json").write_text(json.dumps({"node": "/bundled/node"}))
            self.assertEqual(cli.node_executable(), "/bundled/node")
            with patch.dict(os.environ, {"CAREEROS_NODE": "/override/node"}):
                self.assertEqual(cli.node_executable(), "/override/node")

    def test_renderer_uses_configured_bundled_modules(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(cli, "ROOT", Path(temp)), patch.dict(os.environ, {}, clear=True), \
                patch.object(cli.subprocess, "run") as run:
            root = Path(temp)
            (root / ".runtime.json").write_text(json.dumps({"node": "/bundled/node", "node_path": "/bundled/modules"}))
            cli.render(self.cv, root, root / "test.docx")
            self.assertEqual(run.call_args.args[0][0], "/bundled/node")
            self.assertEqual(run.call_args.kwargs["env"]["NODE_PATH"], "/bundled/modules")

    def test_stale_pdf_cannot_prove_current_page_count(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(cli.subprocess, "run"):
            root = Path(temp)
            docx = root / "test.docx"
            docx.write_text("test placeholder")
            docx.with_suffix(".pdf").write_text("old PDF")
            self.assertIsNone(cli.count_pages(root, docx))

    def test_validate_does_not_sync_or_write_data(self):
        with patch.object(cli.sot, "load_master", return_value=self.master), patch.object(cli.sot, "load_context", return_value=self.context), \
                patch.object(cli.research, "check", return_value=[]), patch.object(cli, "sync_research") as sync, \
                patch.object(cli.tracker, "write") as write:
            cli.cmd_validate(None)
            sync.assert_not_called()
            write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
