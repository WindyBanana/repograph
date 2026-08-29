"""Unit tests for the scanning and analysis layer."""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for package in ("repograph-core", "repograph-render", "repograph-cli", "repograph-tui"):
    sys.path.insert(0, os.path.join(ROOT, "packages", package, "src"))

from repograph_core.languages import analyze  # noqa: E402
from repograph_core.manifests import parse_lockfile, parse_manifest  # noqa: E402
from repograph_core.parsers import load_json, load_toml, load_yaml  # noqa: E402
from repograph_core.resolve import Resolver  # noqa: E402
from repograph_core.security.cvss import base_score, severity_from_score  # noqa: E402
from repograph_core.security.patterns import scan_patterns  # noqa: E402
from repograph_core.security.secrets import scan_secrets  # noqa: E402
from repograph_core.walker import ScanFile, Walker, classify, detect_language  # noqa: E402


class TestWalker(unittest.TestCase):
    def test_language_detection(self):
        self.assertEqual(detect_language("main.py", "main.py")[0], "Python")
        self.assertEqual(detect_language("App.tsx", "src/App.tsx")[0], "TypeScript")
        self.assertEqual(detect_language("Dockerfile", "Dockerfile")[0], "Dockerfile")
        self.assertEqual(detect_language("go.mod", "go.mod")[0], "Go")
        self.assertEqual(detect_language("Makefile", "Makefile")[0], "Make")

    def test_classification(self):
        self.assertEqual(classify("tests/test_x.py", "test_x.py", "Python"), "test")
        self.assertEqual(classify("src/app.py", "app.py", "Python"), "source")
        self.assertEqual(classify("README.md", "README.md", "Markdown"), "docs")
        self.assertEqual(classify("infra/main.tf", "main.tf", "Terraform"), "infra")
        self.assertEqual(classify("package.json", "package.json", "JSON"), "build")

    def test_walk_respects_ignores(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "node_modules", "left-pad"))
            os.makedirs(os.path.join(tmp, "src"))
            for relative, content in (
                ("src/a.py", "x = 1\n"),
                ("node_modules/left-pad/index.js", "//\n"),
                (".gitignore", "secret.txt\n"),
                ("secret.txt", "nope\n"),
            ):
                with open(os.path.join(tmp, relative), "w") as handle:
                    handle.write(content)
            files = Walker(tmp).walk()
            paths = {f.rel for f in files}
            self.assertIn("src/a.py", paths)
            self.assertNotIn("secret.txt", paths)
            self.assertFalse(any(p.startswith("node_modules") for p in paths))


class TestLanguages(unittest.TestCase):
    def test_python(self):
        source = (
            "from fastapi import FastAPI\n"
            "from .db import session\n"
            "app = FastAPI()\n\n"
            "@app.get('/users/{uid}')\n"
            "def get_user(uid):\n"
            "    return {}\n"
        )
        analysis = analyze("Python", "svc/main.py", source)
        self.assertEqual([i.module for i in analysis.imports], ["fastapi", ".db"])
        self.assertEqual(analysis.endpoints[0].path, "/users/{uid}")
        self.assertEqual(analysis.endpoints[0].method, "GET")
        self.assertIn("FastAPI", analysis.frameworks)

    def test_typescript_nest_and_express(self):
        express = "import express from 'express';\nconst app = express();\napp.post('/orders', h);\n"
        analysis = analyze("TypeScript", "src/server.ts", express)
        self.assertEqual(analysis.endpoints[0].method, "POST")
        nest = "@Controller('orders')\nexport class C {\n  @Get(':id')\n  find() {}\n}\n"
        analysis = analyze("TypeScript", "src/orders.controller.ts", nest)
        self.assertEqual(analysis.endpoints[0].path, "/orders/:id")

    def test_go(self):
        source = ('package main\nimport (\n "fmt"\n "github.com/gin-gonic/gin"\n)\n'
                  'func main() {\n r.GET("/health", h)\n}\n')
        analysis = analyze("Go", "cmd/main.go", source)
        self.assertIn("github.com/gin-gonic/gin", [i.module for i in analysis.imports])
        self.assertEqual(analysis.endpoints[0].path, "/health")
        self.assertTrue(analysis.entrypoint)

    def test_unknown_language_is_safe(self):
        analysis = analyze("Brainfuck", "a.bf", "+++[->+<]")
        self.assertEqual(analysis.imports, [])
        self.assertEqual(analysis.endpoints, [])


class TestManifests(unittest.TestCase):
    def test_package_json(self):
        manifest = parse_manifest(
            "package.json",
            '{"name":"web","workspaces":["packages/*"],"dependencies":{"react":"^18.0.0"},'
            '"devDependencies":{"jest":"^29"}}')
        self.assertEqual(manifest.name, "web")
        self.assertEqual(manifest.workspaces, ["packages/*"])
        self.assertEqual(manifest.kind_hint, "frontend")
        scopes = {d.name: d.scope for d in manifest.dependencies}
        self.assertEqual(scopes, {"react": "runtime", "jest": "dev"})

    def test_pyproject_and_go_mod(self):
        manifest = parse_manifest(
            "pyproject.toml",
            '[project]\nname="svc"\ndependencies=["fastapi>=0.1","requests"]\n')
        self.assertEqual(manifest.name, "svc")
        self.assertEqual(len(manifest.dependencies), 2)

        go = parse_manifest("go.mod", "module github.com/a/b\nrequire (\n x/y v1.0.0 // indirect\n)\n")
        self.assertEqual(go.module_path, "github.com/a/b")
        self.assertFalse(go.dependencies[0].direct)

    def test_lockfiles(self):
        deps = parse_lockfile(
            "package-lock.json",
            '{"packages":{"":{},"node_modules/lodash":{"version":"4.17.21"}}}')
        self.assertEqual((deps[0].name, deps[0].version), ("lodash", "4.17.21"))


class TestParsers(unittest.TestCase):
    def test_yaml_subset(self):
        data = load_yaml("services:\n  api:\n    image: node:20\n    ports:\n      - '80:80'\n")
        self.assertEqual(data["services"]["api"]["image"], "node:20")
        self.assertEqual(data["services"]["api"]["ports"], ["80:80"])

    def test_toml_subset(self):
        data = load_toml('[project]\nname = "x"\ndeps = ["a", "b"]\n')
        self.assertEqual(data["project"]["name"], "x")
        self.assertEqual(data["project"]["deps"], ["a", "b"])

    def test_tolerant_json(self):
        self.assertEqual(load_json('{"a": 1, /* c */ "b": [1,2,],}')["b"], [1, 2])


class TestResolver(unittest.TestCase):
    def _files(self, paths):
        out = []
        for path in paths:
            language, prefixes = detect_language(path.rsplit("/", 1)[-1], path)
            out.append(ScanFile(path=path, rel=path, language=language,
                                comment_prefixes=prefixes, kind="source", size=10))
        return out

    def test_python_internal_and_external(self):
        files = self._files(["app/main.py", "app/db.py", "shared/models.py"])
        resolver = Resolver(files, [], {})
        internal = resolver.resolve(files[0], "app.db", 1, False)
        self.assertEqual(internal.internal_file, "app/db.py")
        relative = resolver.resolve(files[0], ".db", 1, True)
        self.assertEqual(relative.internal_file, "app/db.py")
        external = resolver.resolve(files[0], "fastapi", 1, False)
        self.assertEqual((external.external_package, external.ecosystem), ("fastapi", "pypi"))
        stdlib = resolver.resolve(files[0], "os", 1, False)
        self.assertTrue(stdlib.stdlib)

    def test_typescript_alias(self):
        files = self._files(["src/api/client.ts", "src/components/List.tsx"])
        resolver = Resolver(files, [], {"tsconfig.json":
                                        '{"compilerOptions":{"baseUrl":"./src","paths":{"@/*":["*"]}}}'})
        hit = resolver.resolve(files[1], "@/api/client", 1, False)
        self.assertEqual(hit.internal_file, "src/api/client.ts")
        relative = resolver.resolve(files[1], "../api/client", 1, True)
        self.assertEqual(relative.internal_file, "src/api/client.ts")


class TestSecurity(unittest.TestCase):
    def test_secret_detection_and_redaction(self):
        findings = list(scan_secrets("app/config.py", 'KEY = "AKIAIOSFODNN7ZQRSTUV"\n'))
        self.assertEqual(findings[0].severity, "critical")
        self.assertNotIn("AKIAIOSFODNN7ZQRSTUV", findings[0].snippet)

    def test_placeholders_are_ignored(self):
        self.assertEqual(list(scan_secrets("app/config.py", 'KEY = "AKIAIOSFODNN7EXAMPLE"\n')), [])
        self.assertEqual(list(scan_secrets("app/c.py", 'password = "your-password-here"\n')), [])

    def test_pattern_rules(self):
        source = ("import hashlib\n"
                  "cur.execute('SELECT * FROM t WHERE a = %s' % a)\n"
                  "h = hashlib.md5(x)\n"
                  "requests.get(u, verify=False)\n")
        found = {f.cwe for f in scan_patterns("app/x.py", source, "Python")}
        self.assertIn("CWE-89", found)
        self.assertIn("CWE-327", found)
        self.assertIn("CWE-295", found)

    def test_dockerfile_rules(self):
        found = {f.identifier for f in scan_patterns("Dockerfile", "FROM python:latest\n", "Dockerfile")}
        self.assertIn("RG-DOCKER-ROOT", found)
        self.assertIn("RG-DOCKER-LATEST", found)

    def test_cvss(self):
        self.assertEqual(base_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"), 9.8)
        self.assertEqual(severity_from_score(9.8), "critical")
        self.assertIsNone(base_score("nonsense"))


if __name__ == "__main__":
    unittest.main()
