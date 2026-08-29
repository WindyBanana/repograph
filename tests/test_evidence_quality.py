"""A mention is not a use.

Signature matching cannot tell `stripe.Charge.create(...)` from a rule that
detects Stripe or a docs page that recommends it. These tests pin the
difference down, because getting it wrong makes the tool report dozens of
systems for any repository that catalogues names it does not call.
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for package in ("repograph-core", "repograph-render", "repograph-cli", "repograph-tui",
                "repograph-ui"):
    sys.path.insert(0, os.path.join(ROOT, "packages", package, "src"))

from repograph_core.evidence_quality import (  # noqa: E402
    declares_non_security_use,
    is_comment_line,
    is_pattern_catalogue,
    is_pattern_definition,
    is_xml_namespace,
    optional_import_names,
    spans_whole_raw_string,
)
from repograph_core.scan import ScanOptions, scan  # noqa: E402
from repograph_render import agentpack  # noqa: E402


class TestPatternDefinitions(unittest.TestCase):
    def test_it_recognises_a_signature_table_row(self):
        for line in (
            r'''("stripe", "Stripe", "payment", "Stripe", r"stripe|sk_live_\w+"),''',
            r'''    r"(?i)\b(?:DES|RC4|Blowfish)\b|AES/ECB|MODE_ECB",''',
            r'''    (r"postgres|timescale|pgvector", "PostgreSQL", "database", "PostgreSQL"),''',
        ):
            self.assertTrue(is_pattern_definition(line), line)

    def test_it_leaves_ordinary_code_alone(self):
        for line in (
            "completed = subprocess.run(command, shell=True)",
            'query = f"SELECT * FROM orders WHERE id = {order_id}"',
            "eval(user_input)",
            "requests.get(url, verify=False)",
            'password = "hunter2"',
            "client = stripe.Charge.create(amount=100)",
        ):
            self.assertFalse(is_pattern_definition(line), line)

    def test_a_windows_path_is_not_a_regex(self):
        # One signal is not enough: a raw string alone is ordinary in code, and
        # \dev inside a path only looks like the \d class.
        self.assertFalse(is_pattern_definition(r'root = r"C:\Users\dev\project"'))

    def test_a_bare_entry_is_caught_by_the_company_it_keeps(self):
        # r"klarna" carries no regex syntax at all; only the file gives it away.
        table = [
            r'    (r"postgres|timescale", "PostgreSQL", "database", "PostgreSQL"),',
            r'    (r"kafka|redpanda", "Apache Kafka", "queue", "Kafka"),',
            r'    (r"minio", "MinIO", "storage", "MinIO"),',
            r'    (r"klarna", "Klarna", "payment", "Klarna"),',
        ]
        self.assertTrue(is_pattern_catalogue(table))

    def test_real_code_is_not_a_catalogue(self):
        compose = [
            "  image: postgres:16",
            "  image: redis:7",
            "      KAFKA_BROKERS: kafka:9092",
            "  image: minio/minio",
        ]
        self.assertFalse(is_pattern_catalogue(compose))

    def test_a_short_file_is_never_a_catalogue(self):
        # Two matches prove nothing about a file's nature.
        self.assertFalse(is_pattern_catalogue([r'x = r"a\.b|c"', r'y = r"d\.e|f"']))

    def test_a_whole_raw_string_is_a_signature_entry(self):
        self.assertTrue(spans_whole_raw_string(r'(r"clickhouse", "ClickHouse"),', "clickhouse"))
        # ...but a name that is only part of a raw string is a real path.
        self.assertFalse(spans_whole_raw_string(r'cache = r"C:\redis\dump"', "redis"))

    def test_comments_are_prose(self):
        self.assertTrue(is_comment_line("# talks to stripe"))
        self.assertTrue(is_comment_line("// see redis docs"))
        self.assertFalse(is_comment_line("client = stripe.Client()"))


class TestXmlNamespaces(unittest.TestCase):
    """A namespace URI is a name. Nothing ever fetches it."""

    def test_it_recognises_a_vocabulary(self):
        for line, matched in (
            ('"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",', '"http://www.omg.org'),
            ('xmlns:dc="http://purl.org/dc/elements/1.1/"', '"http://purl.org'),
            ('targetNamespace="http://example.test/bpmn"', '"http://example.test'),
            ("'<svg xmlns=\"http://www.w3.org/2000/svg\">'", '"http://www.w3.org'),
        ):
            self.assertTrue(is_xml_namespace(line, matched), line)

    def test_a_real_plaintext_endpoint_still_reports(self):
        for line, matched in (
            ('resp = requests.get("http://api.orders.internal/v1")', '"http://api.orders.internal'),
            ('WEBHOOK = "http://hooks.example.net/notify"', '"http://hooks.example.net'),
        ):
            self.assertFalse(is_xml_namespace(line, matched), line)


class TestOptionalImports(unittest.TestCase):
    def test_it_finds_an_import_with_a_fallback(self):
        source = (
            "try:\n"
            "    import tomllib as _toml\n"
            "except ModuleNotFoundError:\n"
            "    try:\n"
            "        import tomli as _toml\n"
            "    except ModuleNotFoundError:\n"
            "        _toml = None\n"
        )
        self.assertEqual(sorted(set(optional_import_names(source))), ["tomli", "tomllib"])

    def test_a_required_import_is_not_optional(self):
        self.assertEqual(optional_import_names("import os\nimport sys\n"), [])

    def test_an_unrelated_except_does_not_count(self):
        source = "try:\n    import boto3\nexcept ValueError:\n    boto3 = None\n"
        self.assertEqual(optional_import_names(source), [])

    def test_it_stays_linear_on_a_large_file(self):
        # A pattern spanning an arbitrary block body backtracks catastrophically;
        # a scanner that never finishes is worse than one that over-reports.
        source = "try:\n    import foo\nexcept ImportError:\n    foo = None\n" + "x = 1\n" * 40000
        started = time.time()
        self.assertEqual(optional_import_names(source), ["foo"])
        self.assertLess(time.time() - started, 2.0)


class TestNonSecurityHash(unittest.TestCase):
    def test_declared_intent_is_honoured(self):
        self.assertTrue(declares_non_security_use(
            "digest = hashlib.sha1(seed.encode(), usedforsecurity=False).hexdigest()"))

    def test_an_undeclared_digest_still_reports(self):
        self.assertFalse(declares_non_security_use("digest = hashlib.sha1(pw).hexdigest()"))


@unittest.skipIf(os.name == "nt", "these commands are POSIX shell; see shell_supported()")
class TestShellQuoting(unittest.TestCase):
    """These commands run through a shell, so the path must carry its quoting."""

    def test_a_path_with_a_space_survives(self):
        command = agentpack.command_for("claude", "/home/me/My Project/out", "/home/me")
        self.assertIn("'My Project/out/AGENT-INSTRUCTIONS.md'", command)

    def test_a_path_cannot_break_out_of_the_substitution(self):
        # Run it for real: the point is what a shell does with the string, and
        # shlex cannot answer that because it does not expand $( ).
        with tempfile.TemporaryDirectory() as base:
            sentinel = os.path.join(base, "pwned")
            hostile = os.path.join(base, f'x"; touch {sentinel}; "')
            os.makedirs(hostile, exist_ok=True)
            with open(os.path.join(hostile, "AGENT-INSTRUCTIONS.md"), "w") as handle:
                handle.write("instructions\n")
            command = agentpack.command_for("claude", hostile, base)
            # Same shape as the real invocation, with a harmless executable.
            completed = subprocess.run(
                ["sh", "-c", command.replace("claude -p", "printf %s", 1)],
                capture_output=True, cwd=base, check=False,
            )
            self.assertFalse(os.path.exists(sentinel),
                             "the path escaped its quoting and ran a command")
            self.assertIn(b"instructions", completed.stdout)

    def test_an_ordinary_path_is_left_readable(self):
        # Quoting must not make the copy-pasteable command ugly for normal paths.
        self.assertEqual(agentpack.command_for("claude", "/home/me/out", "/home/me"),
                         'claude -p "$(cat out/AGENT-INSTRUCTIONS.md)"')


class TestWindowsDeclinesRatherThanMisleads(unittest.TestCase):
    """cmd.exe leaves $(cat ...) untouched, so the agent would get literal text."""

    def test_the_shell_form_is_declared_posix_only(self):
        self.assertEqual(agentpack.shell_supported(), os.name != "nt")

    def test_the_command_is_still_offered_for_a_posix_shell(self):
        # It runs as written under WSL or Git Bash, so it stays printable.
        self.assertIn("$(cat", agentpack.command_for("claude", "/tmp/out", "/tmp"))


class TestScannerOnACatalogue(unittest.TestCase):
    """End to end: a repository that catalogues vendors does not depend on them."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = cls.tmp.name
        os.makedirs(os.path.join(root, "src"), exist_ok=True)
        with open(os.path.join(root, "src", "signatures.py"), "w") as handle:
            handle.write(
                '"""Detection table for a linter."""\n\n'
                "SIGNATURES = [\n"
                '    ("stripe", "Stripe", r"stripe|sk_live_"),\n'
                '    ("twilio", "Twilio", r"twilio"),\n'
                '    ("klarna", "Klarna", r"klarna"),\n'
                '    ("mongodb", "MongoDB", r"mongodb://|pymongo"),\n'
                '    ("algolia", "Algolia", r"algolia"),\n'
                '    ("auth0", "Auth0", r"auth0"),\n'
                "]\n"
            )
        with open(os.path.join(root, "README.md"), "w") as handle:
            handle.write("# Linter\n\nDetects Stripe, Twilio, Adyen, Braintree and Okta.\n")
        with open(os.path.join(root, "src", "app.py"), "w") as handle:
            handle.write("import redis\n\nclient = redis.Redis(host='cache')\n")
        with open(os.path.join(root, "pyproject.toml"), "w") as handle:
            handle.write('[project]\nname = "linter"\nversion = "0"\n'
                         'dependencies = ["redis==5.0.1"]\n')
        cls.result = scan(ScanOptions(root=root, git_history=False))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def names(self):
        return {system.name for system in self.result.external_systems}

    def test_the_signature_table_creates_no_dependencies(self):
        for phantom in ("Stripe", "Twilio", "Klarna", "MongoDB", "Algolia", "Auth0"):
            self.assertNotIn(phantom, self.names())

    def test_the_readme_creates_no_dependencies(self):
        for phantom in ("Adyen", "Braintree", "Okta"):
            self.assertNotIn(phantom, self.names())

    def test_the_one_real_dependency_is_still_found(self):
        self.assertIn("Redis", self.names())


class TestFindingsKeepTheirPlace(unittest.TestCase):
    """A finding with no location used to collide with its own rule's siblings."""

    def test_two_ecosystems_both_report_a_missing_lockfile(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "api"))
            os.makedirs(os.path.join(root, "web"))
            with open(os.path.join(root, "api", "pyproject.toml"), "w") as handle:
                handle.write('[project]\nname = "api"\nversion = "0"\n'
                             'dependencies = ["requests==2.31.0"]\n')
            with open(os.path.join(root, "api", "main.py"), "w") as handle:
                handle.write("import requests\n\nrequests.get('https://example.test')\n")
            with open(os.path.join(root, "web", "package.json"), "w") as handle:
                handle.write('{"name":"web","dependencies":{"react":"18.2.0"}}\n')
            with open(os.path.join(root, "web", "index.js"), "w") as handle:
                handle.write("import React from 'react';\nexport default React;\n")
            result = scan(ScanOptions(root=root, git_history=False))

        lock = [f for f in result.findings if f.identifier == "RG-DEP-NOLOCK"]
        titles = {f.title for f in lock}
        self.assertIn("No lockfile for the pypi dependencies", titles)
        self.assertIn("No lockfile for the npm dependencies", titles)
        for finding in lock:
            self.assertTrue(finding.file, f"{finding.title} has nowhere to go")


if __name__ == "__main__":
    unittest.main()
