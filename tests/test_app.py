"""Tests for the local Job Search app (app/). Claude calls and portal CLIs are mocked.

Skipped when the app's dependencies (requirements-app.txt) are not installed,
so the framework's own CI, which installs none of them, still passes.
"""

import importlib.util
import os
import tempfile
import unittest
from unittest import mock

HAVE_DEPS = all(importlib.util.find_spec(m) for m in ("fastapi", "httpx", "anthropic", "jinja2", "multipart"))

HEADERS = {"X-JobSearch": "1", "Host": "127.0.0.1:8000"}
POSTING = "We are hiring a data analyst. " * 20


def _fit(**over):
    from app.models import Dimension, FitAssessment, Gate
    base = dict(
        role="Data Analyst", company="Acme",
        eligibility=Gate(verdict="PASS", note=""), language=Gate(verdict="PASS", note=""),
        location=Gate(verdict="PASS", note=""),
        technical_skills=Dimension(score=80, reasoning="r"), experience=Dimension(score=70, reasoning="r"),
        culture=Dimension(score=60, reasoning="r"), career_alignment=Dimension(score=90, reasoning="r"),
        strengths=["SQL"], gaps=["Tableau"], recommendation="Apply.",
    )
    base.update(over)
    return FitAssessment(**base)


@unittest.skipUnless(HAVE_DEPS, "app dependencies not installed (pip install -r requirements-app.txt)")
class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from pathlib import Path
        from app import config
        self.patches = [
            mock.patch.object(config, "DATA_DIR", Path(self.tmp.name)),
            mock.patch.object(config, "DB_PATH", Path(self.tmp.name) / "jobs.db"),
            mock.patch.object(config, "PROFILE_PATH", Path(self.tmp.name) / "profile.json"),
        ]
        for p in self.patches:
            p.start()
        from fastapi.testclient import TestClient
        from app.server import app
        self.client = TestClient(app, headers={"Host": "127.0.0.1:8000"})

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def _profile(self):
        from app.models import Experience, Profile
        profile = Profile(
            name="Test Person", email="t@example.com", primary_skills=["SQL"],
            experience=[
                Experience(title="Analyst", company="Old Co", start="2020", end="Present", bullets=["a", "b", "c"]),
                Experience(title="Intern", company="First Co", start="2019", end="2020", bullets=["x", "y", "z"]),
            ],
        )
        self.client.put("/api/profile", json=profile.model_dump(), headers=HEADERS)
        return profile

    def _add_job(self):
        r = self.client.post("/api/jobs", json={"text": POSTING, "title": "Data Analyst", "company": "Acme"}, headers=HEADERS)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # --- request guards ---

    def test_write_without_header_is_rejected(self):
        r = self.client.post("/api/jobs", json={"text": POSTING})
        self.assertEqual(r.status_code, 403)

    def test_foreign_host_is_rejected(self):
        r = self.client.get("/api/jobs", headers={"Host": "evil.example"})
        self.assertEqual(r.status_code, 403)

    # --- jobs and tracker ---

    def test_add_pasted_job_goes_through_posting_guard(self):
        r = self.client.post("/api/jobs", json={"text": "Data analyst role​ with SQL"}, headers=HEADERS)
        job = r.json()
        self.assertNotIn("​", job["description"])
        self.assertEqual(job["status"], "saved")

    def test_status_change_records_applied_date(self):
        job = self._add_job()
        r = self.client.patch(f"/api/jobs/{job['id']}", json={"status": "applied"}, headers=HEADERS)
        self.assertEqual(r.json()["status"], "applied")
        self.assertTrue(r.json()["applied_at"])
        self.assertEqual(self.client.get("/api/stats").json(), {"applied": 1})

    def test_search_dedupes_by_source_and_id(self):
        from app.models import JobIn
        results = [JobIn(source="linkedin-search", external_id="1", title="A"),
                   JobIn(source="linkedin-search", external_id="2", title="B")]
        with mock.patch("app.sources.search", return_value=results):
            body = {"portals": ["linkedin-search"], "query": "analyst", "location": "London"}
            first = self.client.post("/api/search", json=body, headers=HEADERS).json()
            second = self.client.post("/api/search", json=body, headers=HEADERS).json()
        self.assertEqual((first["added"], second["added"], second["already_seen"]), (2, 0, 2))

    def test_search_reports_portal_errors_without_failing(self):
        from app.sources import SourceError
        with mock.patch("app.sources.search", side_effect=SourceError("linkedin-search: 403")):
            r = self.client.post("/api/search", json={"portals": ["linkedin-search"], "query": "x", "location": "y"}, headers=HEADERS)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["errors"], ["linkedin-search: 403"])

    # --- fit evaluation ---

    def test_evaluate_needs_a_profile(self):
        job = self._add_job()
        r = self.client.post(f"/api/jobs/{job['id']}/evaluate", headers=HEADERS)
        self.assertEqual(r.status_code, 400)

    def test_evaluate_stores_weighted_score(self):
        self._profile()
        job = self._add_job()
        with mock.patch("app.ai.evaluate_fit", return_value=_fit()):
            r = self.client.post(f"/api/jobs/{job['id']}/evaluate", headers=HEADERS)
        out = r.json()
        # 80*.30 + 70*.25 + 60*.15 + 90*.30 = 77.5 -> 78
        self.assertEqual((out["fit_score"], out["fit_verdict"]), (78, "Strong Fit"))

    def test_failed_gate_overrides_score(self):
        from app.models import Gate, verdict_for
        fit = _fit(language=Gate(verdict="FAIL", note="Fluent Polish required"))
        self.assertEqual(verdict_for(fit), "Language mismatch")

    def test_ai_errors_return_readable_message(self):
        from app.ai import AIError
        self._profile()
        job = self._add_job()
        with mock.patch("app.ai.evaluate_fit", side_effect=AIError("Invalid or missing Anthropic API key.")):
            r = self.client.post(f"/api/jobs/{job['id']}/evaluate", headers=HEADERS)
        self.assertEqual(r.status_code, 502)
        self.assertIn("API key", r.json()["detail"])

    # --- documents ---

    def test_cv_takes_titles_and_dates_from_profile_only(self):
        from app.models import CVContent, CoverLetter, SkillGroup, TailoredDocuments, TailoredExperience
        self._profile()
        job = self._add_job()
        docs = TailoredDocuments(
            cv=CVContent(headline="Data Analyst", summary="Summary.", skill_groups=[SkillGroup(name="Data", items=["SQL"])],
                         experience=[TailoredExperience(source_index=0, bullets=["Built <b>dashboards</b>"]),
                                     TailoredExperience(source_index=7, bullets=["Invented role"])]),
            cover_letter=CoverLetter(recipient="Hiring Manager", paragraphs=["Para one."], closing="Kind regards"),
            keywords_covered=["SQL"], keywords_missing=["Tableau"],
        )
        with mock.patch("app.ai.tailor_documents", return_value=docs):
            self.client.post(f"/api/jobs/{job['id']}/documents", json={}, headers=HEADERS)
        cv = self.client.get(f"/jobs/{job['id']}/cv").text
        self.assertIn("Analyst", cv)
        self.assertIn("Old Co", cv)
        self.assertIn("&lt;b&gt;dashboards", cv)          # model output is escaped
        self.assertNotIn("Invented role", cv)              # out-of-range index dropped
        self.assertIn("First Co", cv)                      # omitted role kept
        self.assertIn("<li>x</li>", cv)                    # with its original bullets
        self.assertNotIn("<li>z</li>", cv)                 # trimmed to two
        cover = self.client.get(f"/jobs/{job['id']}/cover").text
        self.assertIn("Dear Hiring Manager", cover)
        self.assertIn("Test Person", cover)


class SourcesTest(unittest.TestCase):
    @unittest.skipUnless(HAVE_DEPS, "app dependencies not installed")
    def test_lists_shipped_portals_with_enabled_flag(self):
        from app.sources import list_portals
        portals = {p["name"]: p for p in list_portals()}
        self.assertIn("linkedin-search", portals)
        self.assertTrue(portals["linkedin-search"]["enabled"])
        self.assertFalse(portals["jobindex-search"]["enabled"])


if __name__ == "__main__":
    unittest.main()
