"""Tests for the optional AI layer: the request, the contract and the merge."""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for package in ("repograph-core", "repograph-render", "repograph-cli", "repograph-tui"):
    sys.path.insert(0, os.path.join(ROOT, "packages", package, "src"))

from repograph_core import enrich  # noqa: E402
from repograph_core.model import ScanResult  # noqa: E402
from repograph_core.scan import ScanOptions, scan  # noqa: E402
from repograph_render import agentpack  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "sample-monorepo")


class TestRequest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = scan(ScanOptions(root=SAMPLE, git_history=False))
        cls.request = enrich.build_request(cls.result)

    def test_questions_are_targeted_and_bounded(self):
        questions = self.request["questions"]
        self.assertTrue(questions)
        self.assertLessEqual(len(questions), 40)
        for question in questions:
            self.assertTrue(question["id"])
            self.assertTrue(question["question"])
            self.assertIn("look_at", question)

    def test_every_target_id_is_real(self):
        known = ({a.id for a in self.result.apps} | {c.id for c in self.result.components}
                 | {f.id for f in self.result.flows} | {f.id for f in self.result.findings})
        diagrams = set(self.request["ids"]["diagrams"])
        for question in self.request["questions"]:
            target = question["target"]
            if not target:
                continue
            pool = diagrams if question["kind"] == "diagram" else known
            self.assertIn(target, pool, f"question {question['id']} targets an unknown id")

    def test_diagram_questions_only_cover_diagrams_that_exist(self):
        produced = set(self.request["ids"]["diagrams"])
        artifacts = self.result.profile.get("artifacts", {})
        for name in produced:
            self.assertTrue(artifacts.get(name, {}).get("include", True),
                            f"asked about {name}, which this scan does not produce")

    def test_id_map_is_published_for_the_agent(self):
        ids = self.request["ids"]
        self.assertEqual(len(ids["applications"]), len(self.result.apps))
        self.assertEqual(len(ids["findings"]), len(self.result.findings))

    def test_low_confidence_findings_are_queued_for_review(self):
        targets = {q["target"] for q in self.request["questions"] if q["kind"] == "finding"}
        uncertain = [f.id for f in self.result.findings
                     if f.confidence in ("low", "medium") and f.category == "code"]
        self.assertTrue(set(uncertain) & targets, "expected uncertain findings to be queued")

    def test_high_severity_uncertainty_comes_first(self):
        priorities = [q["priority"] for q in self.request["questions"]]
        self.assertEqual(priorities, sorted(priorities))


class TestMerge(unittest.TestCase):
    def setUp(self):
        self.result = scan(ScanOptions(root=SAMPLE, git_history=False))
        self.app = self.result.apps[0]
        self.finding = next(f for f in self.result.findings if f.file)

    def merge(self, data, **kwargs):
        return enrich.apply(self.result, data, **kwargs)

    def base(self, **extra):
        payload = {"schema": enrich.ENRICHMENT_SCHEMA,
                   "generated_by": {"tool": "test", "model": "m"}}
        payload.update(extra)
        return payload

    def test_valid_contributions_are_merged(self):
        enrichment, rejected = self.merge(self.base(
            applications=[{"id": self.app.id, "summary": "Does a thing.",
                           "responsibilities": ["one", "two"]}],
            findings=[{"id": self.finding.id, "assessment": "false_positive",
                       "reasoning": "The input is a constant."}],
            insights=[{"kind": "risk", "title": "A real risk", "detail": "why",
                       "severity": "high", "evidence": ["apps/api/app/db.py:14"]}],
        ))
        self.assertEqual(rejected, [])
        self.assertEqual(self.app.ai_summary, "Does a thing.")
        self.assertEqual(self.app.ai_responsibilities, ["one", "two"])
        self.assertEqual(self.finding.ai_assessment, "false_positive")
        self.assertEqual(len(enrichment.insights), 1)
        self.assertTrue(self.result.ai.present)
        self.assertEqual(enrichment.answered_questions, 3)

    def test_unknown_ids_are_rejected(self):
        _, rejected = self.merge(self.base(
            applications=[{"id": "app-not-real", "summary": "x"}],
            findings=[{"id": "nope", "assessment": "true_positive", "reasoning": "y"}],
        ))
        self.assertEqual(len(rejected), 2)
        self.assertIn("does not exist", rejected[0])

    def test_risks_without_evidence_are_dropped(self):
        enrichment, rejected = self.merge(self.base(
            insights=[{"kind": "risk", "title": "Unsupported", "severity": "critical"}]))
        self.assertEqual(enrichment.insights, [])
        self.assertIn("no path:line evidence", rejected[0])

    def test_unsupported_risks_can_be_allowed_explicitly(self):
        enrichment, rejected = self.merge(
            self.base(insights=[{"kind": "risk", "title": "Unsupported"}]),
            require_evidence=False)
        self.assertEqual(len(enrichment.insights), 1)
        self.assertEqual(rejected, [])

    def test_invalid_assessment_is_rejected(self):
        _, rejected = self.merge(self.base(
            findings=[{"id": self.finding.id, "assessment": "probably fine", "reasoning": "r"}]))
        self.assertTrue(rejected)
        self.assertEqual(self.finding.ai_assessment, "")

    def test_assessment_without_reasoning_is_rejected(self):
        _, rejected = self.merge(self.base(
            findings=[{"id": self.finding.id, "assessment": "false_positive", "reasoning": " "}]))
        self.assertIn("without reasoning", rejected[0])

    def test_unknown_targets_are_stripped_but_insight_survives(self):
        enrichment, rejected = self.merge(self.base(
            insights=[{"kind": "observation", "title": "Note", "targets": ["ghost"],
                       "evidence": ["a.py:1"]}]))
        self.assertEqual(len(enrichment.insights), 1)
        self.assertEqual(enrichment.insights[0].targets, [])
        self.assertTrue(rejected)

    def test_evidence_must_look_like_a_path(self):
        enrichment, _ = self.merge(self.base(
            insights=[{"kind": "observation", "title": "Note",
                       "evidence": ["apps/api/app/db.py:14", "trust me", "https://example.com"]}]))
        self.assertEqual(enrichment.insights[0].evidence, ["apps/api/app/db.py:14"])

    def test_line_ranges_and_lists_are_valid_citations(self):
        """Real agents cite blocks, not single lines."""
        enrichment, rejected = self.merge(self.base(
            insights=[{"kind": "risk", "title": "Cited with a range",
                       "evidence": ["apps/api/app/routers/orders.py:22-28",
                                    "apps/api/app/services/order_service.py:16,42",
                                    "apps/api/app/config.py"]}]))
        self.assertEqual(rejected, [])
        self.assertEqual(len(enrichment.insights[0].evidence), 3)

    def test_enrichment_survives_a_json_round_trip(self):
        self.merge(self.base(applications=[{"id": self.app.id, "summary": "Round trip."}]))
        restored = ScanResult.from_dict(json.loads(self.result.to_json()))
        self.assertTrue(restored.ai.present)
        self.assertEqual(restored.apps[0].ai_summary, "Round trip.")
        self.assertEqual(restored.ai.provenance.tool, "test")


class TestAgentPack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = scan(ScanOptions(root=SAMPLE, git_history=False))

    def test_pack_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = agentpack.write(self.result, tmp, SAMPLE)
            names = {os.path.relpath(p, tmp) for p in written}
            self.assertIn("AGENT-INSTRUCTIONS.md", names)
            self.assertIn(os.path.join("agent", "enrichment-request.json"), names)
            self.assertIn(os.path.join("agent", "enrichment.schema.json"), names)
            self.assertIn(os.path.join("agent", "enrichment.example.json"), names)
            with open(os.path.join(tmp, "AGENT-INSTRUCTIONS.md"), encoding="utf-8") as handle:
                instructions = handle.read()
            self.assertIn("AI-REPORT.md", instructions)
            self.assertIn("repograph enrich", instructions)
            self.assertIn("Cite or stay silent", instructions)
            with open(os.path.join(tmp, "agent", "enrichment.example.json")) as handle:
                example = json.load(handle)
            self.assertEqual(example["schema"], enrich.ENRICHMENT_SCHEMA)

    def test_commands_reference_the_instructions(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = agentpack.command_for("claude", tmp, SAMPLE)
            self.assertIn("AGENT-INSTRUCTIONS.md", command)
            self.assertTrue(command.startswith("claude "))

    def test_panel_is_honest_about_privacy(self):
        html = agentpack.panel_html(self.result, "/tmp/out", SAMPLE, tools=[])
        self.assertIn("repograph\nitself never calls a model", html.replace("  ", "\n"))
        self.assertIn("AGENT-INSTRUCTIONS.md", html)


class TestRealAgentOutput(unittest.TestCase):
    """A real enrichment written by a coding agent against the sample monorepo.

    It is checked in so the contract is regression-tested against something an
    actual model produced, not only against hand-written fixtures.
    """

    def test_it_merges_cleanly(self):
        result = scan(ScanOptions(root=SAMPLE, git_history=False))
        with open(os.path.join(ROOT, "examples", "agent-enrichment.example.json")) as handle:
            data = json.load(handle)
        enrichment, rejected = enrich.apply(result, data)
        self.assertEqual(rejected, [], "the checked-in example must merge without rejections")
        self.assertGreater(enrichment.answered_questions, 10)
        self.assertTrue(all(app.ai_summary for app in result.apps))
        assessed = [f for f in result.findings if f.ai_assessment]
        self.assertTrue(assessed)
        self.assertTrue(any(f.ai_assessment == "false_positive" for f in assessed),
                        "a useful review disagrees with the scanner somewhere")
        for finding in assessed:
            self.assertTrue(finding.ai_reasoning)

    def test_every_risk_carries_evidence(self):
        result = scan(ScanOptions(root=SAMPLE, git_history=False))
        with open(os.path.join(ROOT, "examples", "agent-enrichment.example.json")) as handle:
            data = json.load(handle)
        enrichment, _ = enrich.apply(result, data)
        for insight in enrichment.insights:
            if insight.kind == "risk":
                self.assertTrue(insight.evidence, f"risk '{insight.title}' has no evidence")


class TestAgentsFile(unittest.TestCase):
    """The opt-in pointer written into a repository's AGENTS.md / CLAUDE.md."""

    @classmethod
    def setUpClass(cls):
        cls.result = scan(ScanOptions(root=SAMPLE, git_history=False))

    def test_creates_a_file_when_none_exists(self):
        with tempfile.TemporaryDirectory() as repo:
            path, action = agentpack.write_agents_md(self.result, os.path.join(repo, "out"), repo)
            self.assertEqual(action, "created")
            with open(path, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("AI-REPORT.md", content)
            self.assertIn(agentpack.MARKER_START, content)

    def test_appends_without_touching_existing_content(self):
        with tempfile.TemporaryDirectory() as repo:
            target = os.path.join(repo, "AGENTS.md")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("# House rules\n\nAlways run the tests.\n")
            _, action = agentpack.write_agents_md(self.result, os.path.join(repo, "out"), repo)
            self.assertEqual(action, "updated")
            with open(target, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("Always run the tests.", content)
            self.assertIn(agentpack.MARKER_START, content)

    def test_replaces_only_its_own_block(self):
        with tempfile.TemporaryDirectory() as repo:
            target = os.path.join(repo, "AGENTS.md")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(f"before\n{agentpack.MARKER_START}\nstale\n"
                             f"{agentpack.MARKER_END}\nafter\n")
            _, action = agentpack.write_agents_md(self.result, os.path.join(repo, "out"), repo)
            self.assertEqual(action, "updated")
            with open(target, encoding="utf-8") as handle:
                content = handle.read()
            self.assertTrue(content.startswith("before"))
            self.assertTrue(content.rstrip().endswith("after"))
            self.assertNotIn("stale", content)

    def test_second_run_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as repo:
            agentpack.write_agents_md(self.result, os.path.join(repo, "out"), repo)
            _, action = agentpack.write_agents_md(self.result, os.path.join(repo, "out"), repo)
            self.assertEqual(action, "unchanged")


class TestEnrichCli(unittest.TestCase):
    def test_cli_merges_and_rerenders(self):
        from repograph_cli.main import main

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["scan", SAMPLE, "-o", tmp, "--quiet", "--no-git",
                                   "--format", "json,agent"]), 0)
            request_path = enrich.request_path(tmp)
            self.assertTrue(os.path.exists(request_path))
            with open(request_path) as handle:
                request = json.load(handle)
            app_id = next(iter(request["ids"]["applications"]))
            with open(enrich.enrichment_path(tmp), "w") as handle:
                json.dump({"schema": enrich.ENRICHMENT_SCHEMA,
                           "generated_by": {"tool": "test"},
                           "applications": [{"id": app_id, "summary": "Merged by the CLI."}]},
                          handle)
            self.assertEqual(main(["enrich", tmp, "--format", "json"]), 0)
            with open(os.path.join(tmp, "repograph.json")) as handle:
                stored = json.load(handle)
            merged = next(a for a in stored["apps"] if a["id"] == app_id)
            self.assertEqual(merged["ai_summary"], "Merged by the CLI.")
            self.assertTrue(stored["ai"]["present"])

    def test_missing_enrichment_file_is_reported(self):
        from repograph_cli.main import main

        with tempfile.TemporaryDirectory() as tmp:
            main(["scan", SAMPLE, "-o", tmp, "--quiet", "--no-git", "--format", "json"])
            self.assertEqual(main(["enrich", tmp]), 2)


if __name__ == "__main__":
    unittest.main()
