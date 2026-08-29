"""Tests for the desktop UI server and the packaging wrappers."""

import json
import os
import plistlib
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for package in ("repograph-core", "repograph-render", "repograph-cli", "repograph-tui",
                "repograph-ui"):
    sys.path.insert(0, os.path.join(ROOT, "packages", package, "src"))
sys.path.insert(0, os.path.join(ROOT, "packaging"))

import bundle  # noqa: E402
from repograph_ui import server as ui_server  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "sample-monorepo")


class UiHarness:
    """Runs the UI server on a free port for the duration of a test class."""

    def __init__(self):
        self.token = "test-token-" + os.urandom(4).hex()
        self.port = ui_server.free_port(7800)
        handler = type("TestHandler", (ui_server.Handler,),
                       {"token": self.token, "job": ui_server.Job()})
        self.httpd = ui_server.Server(("127.0.0.1", self.port), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, path, with_token=True):
        base = f"http://127.0.0.1:{self.port}{path}"
        if not with_token:
            return base
        return base + ("&" if "?" in path else "?") + "t=" + self.token

    def get(self, path, with_token=True, headers=None):
        request = urllib.request.Request(self.url(path, with_token),
                                         headers=headers or {})
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()

    def post(self, path, payload):
        request = urllib.request.Request(
            self.url(path), data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())


class TestUiServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = UiHarness()

    @classmethod
    def tearDownClass(cls):
        cls.ui.stop()

    def test_the_page_loads_without_a_token(self):
        status, body = self.ui.get("/", with_token=False)
        self.assertEqual(status, 200)
        self.assertIn(b"repograph", body)
        self.assertIn(b"__TOKEN__", body)

    def test_the_api_refuses_requests_without_the_token(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.ui.get("/api/status", with_token=False)
        self.assertEqual(caught.exception.code, 403)

    def test_the_api_refuses_a_wrong_token(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.ui.get("/api/status&t=nope", with_token=False)
        self.assertEqual(caught.exception.code, 403)

    def test_cross_origin_requests_are_refused(self):
        """A page on the internet must not be able to drive a local scanner."""
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.ui.get("/api/status", headers={"Origin": "https://evil.example"})
        self.assertEqual(caught.exception.code, 403)

    def test_browse_lists_directories(self):
        status, body = self.ui.get("/api/browse?path=" + ROOT)
        self.assertEqual(status, 200)
        data = json.loads(body)
        names = {entry["name"] for entry in data["entries"]}
        self.assertIn("packages", names)
        self.assertIn("examples", names)
        self.assertTrue(data["parent"])

    def test_browse_falls_back_to_home_for_a_bad_path(self):
        _, body = self.ui.get("/api/browse?path=/definitely/not/here")
        self.assertEqual(json.loads(body)["path"], os.path.expanduser("~"))

    def test_a_scan_runs_and_reports_its_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = self.ui.post("/api/scan",
                                           {"path": SAMPLE, "output": tmp, "no_git": True})
            self.assertEqual(status, 200)
            self.assertTrue(payload["started"])

            deadline = time.time() + 120
            state = "running"
            while time.time() < deadline:
                _, body = self.ui.get("/api/status")
                snapshot = json.loads(body)
                state = snapshot["state"]
                if state != "running":
                    break
                time.sleep(0.3)

            self.assertEqual(state, "done", snapshot.get("error"))
            self.assertEqual(snapshot["summary"]["apps"], 4)
            self.assertTrue(snapshot["questions"])
            self.assertIn("report.pdf", snapshot["documents"])
            self.assertTrue(os.path.exists(os.path.join(tmp, "index.html")))

            _, report = self.ui.get("/report/index.html")
            self.assertIn(b"repograph", report)

    def test_the_report_route_refuses_paths_outside_the_output(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.ui.get("/report/../../../../etc/passwd")
        self.assertEqual(caught.exception.code, 404)

    def test_a_bad_scan_request_is_reported_not_crashed(self):
        self.ui.post("/api/scan", {"path": "/does/not/exist"})
        deadline = time.time() + 20
        while time.time() < deadline:
            _, body = self.ui.get("/api/status")
            snapshot = json.loads(body)
            if snapshot["state"] != "running":
                break
            time.sleep(0.2)
        self.assertEqual(snapshot["state"], "error")
        self.assertIn("not a folder", snapshot["error"])


class TestBundles(unittest.TestCase):
    def _fake_binary(self, directory: str) -> str:
        path = os.path.join(directory, "repograph")
        with open(path, "w") as handle:
            handle.write("#!/bin/sh\necho repograph\n")
        os.chmod(path, 0o755)
        return path

    def test_macos_app_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = self._fake_binary(tmp)
            app = bundle.macos_app(binary, tmp)
            self.assertTrue(os.path.isdir(app))
            executable = os.path.join(app, "Contents", "MacOS", "repograph")
            self.assertTrue(os.access(executable, os.X_OK))
            with open(os.path.join(app, "Contents", "Info.plist"), "rb") as handle:
                info = plistlib.load(handle)
            self.assertEqual(info["CFBundleExecutable"], "repograph")
            self.assertEqual(info["CFBundleIdentifier"], bundle.BUNDLE_ID)
            # double-clicking must open the UI, not print CLI usage into the void
            self.assertEqual(info["LSEnvironment"]["REPOGRAPH_FORCE_UI"], "1")

    def test_linux_desktop_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = self._fake_binary(tmp)
            entry = bundle.linux_desktop_entry(binary, tmp)
            with open(entry, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("[Desktop Entry]", content)
            self.assertIn(f"Exec={binary}", content)
            self.assertIn("Terminal=false", content)
            self.assertTrue(os.path.exists(os.path.join(tmp, "repograph.svg")))

    def test_windows_shortcut_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = bundle.windows_shortcut_script(r"C:\repograph.exe", tmp)
            with open(script, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("CreateShortcut", content)
            self.assertIn(r"C:\repograph.exe", content)


class TestPackagedEntryPoint(unittest.TestCase):
    def test_it_chooses_the_ui_when_nothing_is_watching(self):
        import entry

        os.environ["REPOGRAPH_FORCE_UI"] = "1"
        try:
            self.assertTrue(entry._launched_from_a_desktop())
        finally:
            del os.environ["REPOGRAPH_FORCE_UI"]

        os.environ["REPOGRAPH_FORCE_CLI"] = "1"
        try:
            self.assertFalse(entry._launched_from_a_desktop())
        finally:
            del os.environ["REPOGRAPH_FORCE_CLI"]


if __name__ == "__main__":
    unittest.main()
