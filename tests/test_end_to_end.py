"""End-to-end tests: scan the bundled example monorepo and render every format."""

import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for package in ("repograph-core", "repograph-render", "repograph-cli", "repograph-tui"):
    sys.path.insert(0, os.path.join(ROOT, "packages", package, "src"))

from repograph_core.model import ScanResult  # noqa: E402
from repograph_core.scan import ScanOptions, scan  # noqa: E402
from repograph_render.render import render_all  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "sample-monorepo")


class TestSampleScan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = scan(ScanOptions(root=SAMPLE, git_history=False))

    def test_detects_every_application(self):
        names = {app.name for app in self.result.apps}
        self.assertEqual(names, {"acme-api", "@acme/web", "acme-worker", "acme-shared"})

    def test_application_kinds(self):
        kinds = {app.name: app.kind for app in self.result.apps}
        self.assertEqual(kinds["acme-api"], "service")
        self.assertEqual(kinds["@acme/web"], "frontend")
        self.assertEqual(kinds["acme-worker"], "job")
        self.assertEqual(kinds["acme-shared"], "library")

    def test_layered_style_detected_for_api(self):
        api = next(a for a in self.result.apps if a.name == "acme-api")
        self.assertIn("Layered", api.architecture_style)

    def test_http_endpoints(self):
        routes = {(e.method, e.path) for e in self.result.endpoints if e.kind == "http"}
        self.assertIn(("GET", "/orders/{order_id}"), routes)
        self.assertIn(("POST", "/orders"), routes)
        self.assertIn(("GET", "/health"), routes)

    def test_celery_tasks_are_event_entrypoints(self):
        tasks = [e for e in self.result.endpoints if e.kind == "event"]
        self.assertTrue(tasks, "expected the celery tasks to be detected")

    def test_external_systems(self):
        names = {s.name for s in self.result.external_systems}
        for expected in ("PostgreSQL", "Redis", "Apache Kafka", "Stripe", "AWS S3"):
            self.assertIn(expected, names)

    def test_cross_application_dependency(self):
        by_id = {a.id: a.name for a in self.result.apps}
        edges = {(by_id.get(e.source), by_id.get(e.target))
                 for e in self.result.edges if e.kind == "depends"}
        self.assertIn(("acme-api", "acme-shared"), edges)
        self.assertIn(("acme-worker", "acme-shared"), edges)

    def test_security_findings(self):
        identifiers = {f.identifier for f in self.result.findings}
        self.assertIn("RG-SECRET-PASSWORD-ASSIGN", identifiers)
        self.assertIn("RG-SECRET-CONN-STRING", identifiers)
        self.assertIn("RG-PY-SQL-FORMAT", identifiers)
        self.assertIn("RG-TLS-VERIFY-OFF", identifiers)
        self.assertIn("RG-TF-PUBLIC-BUCKET", identifiers)
        self.assertIn("RG-TF-PUBLIC-INGRESS", identifiers)
        self.assertTrue(any(f.severity == "high" for f in self.result.findings))

    def test_findings_carry_locations(self):
        for finding in self.result.findings:
            if finding.category in ("secret", "code", "infra"):
                self.assertTrue(finding.file, f"{finding.identifier} has no file")
                self.assertTrue(finding.remediation, f"{finding.identifier} has no remediation")

    def test_infrastructure(self):
        infra = self.result.infrastructure
        services = {c["name"] for c in infra["containers"]}
        self.assertEqual(services, {"api", "web", "worker", "db", "cache", "broker"})
        self.assertEqual(len(infra["dockerfiles"]), 3)
        self.assertTrue(infra["terraform"])
        self.assertTrue(infra["ci"])
        self.assertIn("DATABASE_URL", infra["env_vars"])

    def test_dependency_reconciliation(self):
        by_name = {d.name: d for d in self.result.dependencies}
        self.assertTrue(by_name["fastapi"].used)
        self.assertEqual(by_name["lodash"].version, "*")
        missing = {f.package for f in self.result.findings if f.identifier == "RG-DEP-MISSING"}
        self.assertIn("kafka", missing)  # imported by the API, never declared

    def test_flows_have_lanes_and_ends(self):
        self.assertTrue(self.result.flows)
        flow = self.result.flows[0]
        self.assertTrue(flow.lanes)
        kinds = {node.kind for node in flow.nodes}
        self.assertIn("start", kinds)
        self.assertIn("end", kinds)

    def test_model_round_trips(self):
        payload = json.loads(self.result.to_json())
        restored = ScanResult.from_dict(payload)
        self.assertEqual(len(restored.apps), len(self.result.apps))
        self.assertEqual(restored.metrics.loc, self.result.metrics.loc)
        self.assertEqual(restored.apps[0].name, self.result.apps[0].name)

    def test_summary_is_populated(self):
        summary = self.result.summary
        self.assertEqual(summary["shape"], "monorepo")
        self.assertIn("Python", summary["primary_languages"])
        self.assertIn(summary["risk_level"], ("critical", "high", "medium", "low"))


class TestRenderAll(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = scan(ScanOptions(root=SAMPLE, git_history=False))
        cls.tmp = tempfile.TemporaryDirectory()
        cls.rendered = render_all(cls.result, cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def path(self, *parts):
        return os.path.join(self.tmp.name, *parts)

    def test_expected_files_exist(self):
        for name in ("index.html", "report.md", "AI-REPORT.md", "repograph.json", "report.pdf",
                     "report.xlsx", "presentation.pptx", "sbom.cdx.json", "sbom.spdx.json",
                     "MANIFEST.json", "README.md", "data/findings.csv",
                     "models/archimate.xml"):
            self.assertTrue(os.path.exists(self.path(*name.split("/"))), f"missing {name}")
        self.assertEqual(self.rendered.skipped, {})

    def test_html_report_is_self_contained(self):
        with open(self.path("index.html"), encoding="utf-8") as handle:
            html = handle.read()
        self.assertIn("<canvas id=\"graph2d\">", html)
        self.assertIn("<canvas id=\"graph3d\">", html)
        self.assertIn("window.__REPOGRAPH__", html)
        self.assertNotIn("http://cdn", html)
        self.assertNotIn("<script src=", html)
        for tab in ("Architecture", "Process flows", "Vulnerabilities", "AI report"):
            self.assertIn(tab, html)

    def test_svg_diagrams_are_wellformed_and_unique(self):
        directory = self.path("diagrams")
        svgs = [f for f in os.listdir(directory) if f.endswith(".svg")]
        self.assertGreater(len(svgs), 4)
        seen_ids = set()
        for name in svgs:
            with open(os.path.join(directory, name), encoding="utf-8") as handle:
                content = handle.read()
            ET.fromstring(content)  # raises if malformed
            for marker in ("arrow-", "soft-"):
                index = content.find(f'id="{marker}')
                if index >= 0:
                    ident = content[index + 4: content.find('"', index + 4)]
                    self.assertNotIn(ident, seen_ids, "duplicate SVG id across diagrams")
                    seen_ids.add(ident)

    def test_bpmn_and_archimate_are_valid_xml(self):
        bpmn_dir = self.path("diagrams", "bpmn")
        for name in os.listdir(bpmn_dir):
            root = ET.parse(os.path.join(bpmn_dir, name)).getroot()
            self.assertTrue(root.tag.endswith("definitions"))
        archimate = ET.parse(self.path("models", "archimate.xml")).getroot()
        self.assertTrue(archimate.tag.endswith("model"))

    def test_office_documents_are_zip_packages(self):
        with zipfile.ZipFile(self.path("report.xlsx")) as book:
            self.assertIn("xl/workbook.xml", book.namelist())
            self.assertIsNone(book.testzip())
        with zipfile.ZipFile(self.path("presentation.pptx")) as deck:
            self.assertIn("ppt/presentation.xml", deck.namelist())
            self.assertIsNone(deck.testzip())

    def test_pdf_header_and_trailer(self):
        with open(self.path("report.pdf"), "rb") as handle:
            data = handle.read()
        self.assertTrue(data.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", data[-64:])
        self.assertIn(b"/Type /Catalog", data)

    def test_sbom_shape(self):
        with open(self.path("sbom.cdx.json"), encoding="utf-8") as handle:
            sbom = json.load(handle)
        self.assertEqual(sbom["bomFormat"], "CycloneDX")
        self.assertTrue(sbom["components"])
        with open(self.path("sbom.spdx.json"), encoding="utf-8") as handle:
            spdx = json.load(handle)
        self.assertEqual(spdx["spdxVersion"], "SPDX-2.3")

    def test_ai_report_mentions_limits(self):
        with open(self.path("AI-REPORT.md"), encoding="utf-8") as handle:
            report = handle.read()
        self.assertIn("LIMITS OF THIS ANALYSIS", report)
        self.assertIn("acme-api", report)
        self.assertIn("PostgreSQL", report)

    def test_manifest_lists_written_files(self):
        with open(self.path("MANIFEST.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertIn("index.html", manifest["files"])
        self.assertEqual(manifest["summary"]["applications"], 4)


class TestCli(unittest.TestCase):
    def test_scan_command_writes_output(self):
        from repograph_cli.main import main

        with tempfile.TemporaryDirectory() as tmp:
            code = main(["scan", SAMPLE, "-o", tmp, "--format", "json,csv", "--quiet", "--no-git"])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(os.path.join(tmp, "repograph.json")))
            self.assertTrue(os.path.exists(os.path.join(tmp, "data", "findings.csv")))

    def test_unknown_format_is_rejected(self):
        from repograph_cli.main import _formats

        with self.assertRaises(SystemExit):
            _formats("html,nope")


if __name__ == "__main__":
    unittest.main()


class TestInferredPurpose(unittest.TestCase):
    """The README can be stale, so purpose is also derived from the code."""

    @classmethod
    def setUpClass(cls):
        cls.result = scan(ScanOptions(root=SAMPLE, git_history=False))

    def by_name(self, name):
        return next(a for a in self.result.apps if a.name == name)

    def test_api_purpose_names_its_domain_and_stores(self):
        purpose = self.by_name("acme-api").purpose
        self.assertIn("Backend service", purpose)
        self.assertIn("order", purpose)
        self.assertIn("PostgreSQL", purpose)
        self.assertIn("acme-shared", purpose)

    def test_library_purpose_names_its_consumers(self):
        purpose = self.by_name("acme-shared").purpose
        self.assertIn("Shared library", purpose)
        self.assertIn("acme-api", purpose)

    def test_frontend_is_not_credited_with_backend_stores(self):
        purpose = self.by_name("@acme/web").purpose
        self.assertIn("User interface", purpose)
        self.assertNotIn("PostgreSQL", purpose)
        self.assertNotIn("Kafka", purpose)

    def test_worker_reports_event_triggers(self):
        purpose = self.by_name("acme-worker").purpose
        self.assertIn("Background worker", purpose)
        self.assertIn("event", purpose)
