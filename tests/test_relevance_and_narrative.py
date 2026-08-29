"""Tests for the judgement layer: what is worth producing, and how it reads."""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for package in ("repograph-core", "repograph-render", "repograph-cli", "repograph-tui"):
    sys.path.insert(0, os.path.join(ROOT, "packages", package, "src"))

from repograph_core import ask, narrative  # noqa: E402
from repograph_core.scan import ScanOptions, scan  # noqa: E402
from repograph_render import mermaid  # noqa: E402
from repograph_render.diagrams import build_all, describe  # noqa: E402
from repograph_render.render import render_all  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "sample-monorepo")


def make_docs_repo(directory: str) -> None:
    os.makedirs(os.path.join(directory, "docs"), exist_ok=True)
    for name in ("intro", "setup", "faq", "style", "ops"):
        with open(os.path.join(directory, "docs", f"{name}.md"), "w") as handle:
            handle.write(f"# {name}\n\nGuidance about {name}.\n" * 4)
    with open(os.path.join(directory, "README.md"), "w") as handle:
        handle.write("# Handbook\n\nHow we work.\n")


class TestProfile(unittest.TestCase):
    def test_monorepo_is_recognised(self):
        result = scan(ScanOptions(root=SAMPLE, git_history=False))
        self.assertEqual(result.profile["kind"], "monorepo")
        self.assertTrue(result.profile["signals"])

    def test_documentation_repository_skips_software_diagrams(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_docs_repo(tmp)
            result = scan(ScanOptions(root=tmp, git_history=False))
            self.assertEqual(result.profile["kind"], "documentation")
            artifacts = result.profile["artifacts"]
            for name in ("c4-context", "c4-container", "flows", "deployment", "bpmn", "deck"):
                self.assertFalse(artifacts[name]["include"], f"{name} should be skipped")
                self.assertTrue(artifacts[name]["reason"], f"{name} needs a stated reason")

    def test_a_docs_repository_produces_no_architecture_diagrams(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_docs_repo(tmp)
            result = scan(ScanOptions(root=tmp, git_history=False))
            self.assertEqual(build_all(result), {})
            sources = mermaid.build_all(result)
            self.assertNotIn("c4-context", sources)
            self.assertIn("mindmap", sources)

    def test_everything_forces_all_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_docs_repo(tmp)
            result = scan(ScanOptions(root=tmp, git_history=False, everything=True))
            self.assertTrue(all(entry["include"]
                                for entry in result.profile["artifacts"].values()))

    def test_output_folder_matches_the_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_docs_repo(tmp)
            result = scan(ScanOptions(root=tmp, git_history=False))
            with tempfile.TemporaryDirectory() as out:
                rendered = render_all(result, out)
                self.assertFalse(os.path.exists(os.path.join(out, "presentation.pptx")))
                self.assertFalse(os.path.exists(os.path.join(out, "report.xlsx")))
                self.assertFalse(os.path.exists(os.path.join(out, "models", "archimate.xml")))
                self.assertTrue(os.path.exists(os.path.join(out, "index.html")))
                self.assertTrue(rendered.not_applicable)
                self.assertEqual(rendered.skipped, {})

    def test_single_library_skips_the_landscape(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "mylib"))
            with open(os.path.join(tmp, "pyproject.toml"), "w") as handle:
                handle.write('[project]\nname = "mylib"\ndependencies = []\n')
            for name in ("core", "helpers", "api"):
                with open(os.path.join(tmp, "mylib", f"{name}.py"), "w") as handle:
                    handle.write("import os\n\n\ndef do_something():\n    return os.getcwd()\n")
            result = scan(ScanOptions(root=tmp, git_history=False))
            self.assertFalse(result.profile["artifacts"]["application-landscape"]["include"])


class TestNarrative(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = scan(ScanOptions(root=SAMPLE, git_history=False))
        cls.business = cls.result.business

    def test_it_speaks_plainly(self):
        text = " ".join(point["plain"] for group in
                        ("capabilities", "users", "data", "dependencies", "operations", "health")
                        for point in self.business[group])
        for jargon in ("endpoint", "repository", "import", "CWE", "dependency graph"):
            self.assertNotIn(jargon, text, f"'{jargon}' does not belong in the plain summary")

    def test_capabilities_are_grouped_by_subject(self):
        titles = [c["title"] for c in self.business["capabilities"]]
        self.assertIn("Orders", titles)
        self.assertIn("Background work", titles)

    def test_health_checks_are_not_sold_as_a_capability(self):
        orders = next(c for c in self.business["capabilities"] if c["title"] == "Orders")
        self.assertNotIn("health", orders["detail"].lower())

    def test_every_point_keeps_its_technical_depth(self):
        for point in self.business["capabilities"] + self.business["data"]:
            self.assertTrue(point["detail"] or point["evidence"],
                            f"{point['title']} has no detail to expand into")

    def test_data_stores_are_named(self):
        titles = [d["title"] for d in self.business["data"]]
        self.assertIn("PostgreSQL", titles)

    def test_it_admits_what_it_cannot_know(self):
        self.assertTrue(self.business["unknowns"])

    def test_plural_and_verb_agreement(self):
        self.assertEqual(narrative.plural(1, "test file"), "1 test file")
        self.assertEqual(narrative.plural(3, "test file"), "3 test files")
        self.assertEqual(narrative.plural(2, "dependency", "dependencies"), "2 dependencies")
        self.assertEqual(narrative.verb(1, "is", "are"), "is")
        self.assertEqual(narrative.verb(4, "is", "are"), "are")


class TestDiagramCaptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = scan(ScanOptions(root=SAMPLE, git_history=False))
        cls.diagrams = build_all(cls.result)

    def test_every_diagram_gets_explained(self):
        for name, diagram in self.diagrams.items():
            caption = describe(name, diagram, self.result)
            self.assertTrue(caption["what"], f"{name} has no explanation")

    def test_the_notice_is_computed_from_the_graph(self):
        caption = describe("dependency-graph", self.diagrams["dependency-graph"], self.result)
        self.assertIn("depended on by", caption["notice"])
        caption = describe("dependency-layers", self.diagrams["dependency-layers"], self.result)
        self.assertIn("cycle", caption["notice"])


class TestAsk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = scan(ScanOptions(root=SAMPLE, git_history=False))

    def test_suggestions_are_specific_to_this_repository(self):
        questions = ask.suggestions(self.result)
        self.assertTrue(questions)
        joined = " ".join(questions).lower()
        self.assertTrue(any(term in joined for term in ("orders", "kafka", "redis", "shared")),
                        "suggestions should name things from this repository")

    def test_prompt_points_at_the_report_first(self):
        prompt = ask.build_prompt(self.result, "where do I add refunds?", "/tmp/out", SAMPLE)
        self.assertIn("where do I add refunds?", prompt)
        self.assertIn("AI-REPORT.md", prompt)
        self.assertIn("Do not re-derive it", prompt)
        self.assertIn("PostgreSQL", prompt)

    def test_cli_suggest_runs(self):
        from repograph_cli.main import main

        with tempfile.TemporaryDirectory() as tmp:
            main(["scan", SAMPLE, "-o", tmp, "--quiet", "--no-git", "--format", "json"])
            self.assertEqual(main(["ask", "--suggest", "-o", tmp]), 0)
            self.assertEqual(main(["ask", "what breaks first?", "-o", tmp]), 0)
            self.assertTrue(os.path.exists(os.path.join(tmp, "agent", "question.md")))


if __name__ == "__main__":
    unittest.main()
