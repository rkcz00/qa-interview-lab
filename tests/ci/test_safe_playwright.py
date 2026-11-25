"""Synthetic private event logs; no application/database/browser is started."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import playwright_ci as ci


CANARY = "FAKE_PRIVATE_039_VALUE"
PRIVATE = CANARY + " https://fake.invalid/private cookie=fake password=fake X-CSRFToken=fake DATABASE_URL=fake"
SOURCE = "tests/e2e/test_probe.py"
NODE = SOURCE + "::test_answer"


class SafeSummaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="qil039-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        source = self.root / SOURCE
        source.parent.mkdir(parents=True)
        source.write_text("def test_answer():\n    value = 1\n    assert value\n\ndef test_timeout():\n    pass\n", encoding="utf-8")
        self.registry = ci.Registry(self.root)

    def event(self, **changes):
        value = {"nodeid": NODE, "exception_type": "AssertionError", "path": SOURCE, "line": 3, "phase": "call"}
        value.update(changes)
        return value

    def document(self, *events):
        return {"version": 1, "complete": True, "events": list(events)}

    def public(self, *events, browser="webkit"):
        return ci.render(browser, ci.sanitize(self.document(*events), self.registry))

    def test_failure_keeps_only_stable_identity_exception_and_source(self):
        result = self.public(self.event())
        self.assertIn("Browser: webkit", result)
        self.assertIn(NODE, result)
        self.assertIn("AssertionError", result)
        self.assertIn(SOURCE + ":3", result)
        self.assertIn("Failed: 1; Errors: 0", result)

    def test_timeout_and_multiple_failures_keep_counts(self):
        result = self.public(self.event(), self.event(nodeid=SOURCE + "::test_timeout", exception_type="TimeoutError", line=5))
        self.assertIn("Failed: 2; Errors: 0", result)
        self.assertIn("TimeoutError", result)
        self.assertIn(SOURCE + "::test_timeout", result)

    def test_messages_stdout_environment_and_parameters_never_pass(self):
        event = self.event(nodeid=NODE + "[" + PRIVATE + "]", message=PRIVATE,
                           traceback="Traceback (most recent call last):\n" + PRIVATE,
                           stdout=PRIVATE, stderr=PRIVATE, environment={"SECRET": PRIVATE})
        result = self.public(event)
        self.assertIn(NODE, result)
        for forbidden in (CANARY, "fake.invalid", "cookie=", "password=", "X-CSRFToken", "DATABASE_URL", "Traceback", str(self.root)):
            self.assertNotIn(forbidden, result)

    def test_unknown_exception_name_is_not_reflected(self):
        result = self.public(self.event(exception_type=PRIVATE))
        self.assertIn("`Exception`", result)
        self.assertNotIn(CANARY, result)

    def test_unknown_or_absolute_node_cannot_inject_a_summary(self):
        for node in (PRIVATE, str(self.root / SOURCE) + "::test_answer", NODE + "\n" + PRIVATE,
                     "tests/e2e/test_probe.py::test_missing", "tests/../e2e/test_probe.py::test_answer"):
            with self.subTest(kind="invalid identity"):
                result = self.public(self.event(nodeid=node))
                self.assertIn("Failed: 1; Errors: 0", result)
                self.assertNotIn(NODE, result)
                self.assertNotIn(CANARY, result)

    def test_location_requires_existing_relative_source_and_real_line(self):
        cases = [{"path": PRIVATE}, {"path": str(self.root / SOURCE)}, {"path": "tests/../private.py"},
                 {"line": 0}, {"line": True}, {"line": 10_000_000}, {"line": "3\n" + PRIVATE}]
        for case in cases:
            with self.subTest(kind="invalid source"):
                result = self.public(self.event(**case))
                self.assertNotIn(NODE, result)
                self.assertNotIn(CANARY, result)
                self.assertNotIn(str(self.root), result)

    def test_setup_teardown_and_collection_are_errors_not_failed_calls(self):
        report = ci.sanitize(self.document(self.event(), self.event(phase="setup"), self.event(phase="teardown"), {"phase": "collect"}), self.registry)
        self.assertEqual((report["failed"], report["errors"]), (1, 3))

    def test_duplicate_parameterized_failures_keep_count_without_repeating_rows(self):
        report = ci.sanitize(self.document(self.event(nodeid=NODE + "[desktop]"), self.event(nodeid=NODE + "[mobile]")), self.registry)
        self.assertEqual(report["failed"], 2)
        self.assertEqual(len(report["rows"]), 1)

    def test_unfinished_or_malformed_event_envelopes_are_rejected(self):
        for document in ({}, {"version": True, "complete": True, "events": []},
                         {"version": 1, "complete": False, "events": []},
                         self.document({"phase": PRIVATE}), self.document(PRIVATE),
                         self.document(*([self.event()] * (ci.MAX_EVENTS + 1)))):
            with self.subTest(kind="invalid envelope"):
                with self.assertRaises((ValueError, TypeError)):
                    ci.sanitize(document, self.registry)

    def test_bad_json_and_oversized_private_files_are_rejected(self):
        path = self.root / "events.json"
        path.write_text(PRIVATE, encoding="utf-8")
        with self.assertRaises(ValueError):
            ci.read_events(path, self.registry)
        path.write_bytes(b"x" * (ci.MAX_INPUT + 1))
        with self.assertRaises(ValueError):
            ci.read_events(path, self.registry)

    def test_symlink_event_is_rejected_before_read(self):
        path = self.root / "events.json"
        with patch.object(Path, "is_symlink", return_value=True), patch.object(Path, "read_text") as read:
            with self.assertRaises(ValueError):
                ci.read_events(path, self.registry)
            read.assert_not_called()

    def test_syntax_error_source_has_no_invented_function(self):
        (self.root / SOURCE).write_text("def broken(:\n", encoding="utf-8")
        registry = ci.Registry(self.root)
        report = ci.sanitize(self.document({"phase": "collect"}), registry)
        self.assertEqual(report, {"failed": 0, "errors": 1, "rows": []})
        self.assertNotIn(NODE, registry.nodes)

    def test_invalid_browser_cannot_inject_markdown(self):
        with self.assertRaises(ValueError):
            self.public(self.event(), browser=PRIVATE)

    def test_report_writes_only_sanitized_step_summary_and_console(self):
        event = self.root / "qil-e2e-test-events.json"
        event.write_text(json.dumps(self.document(self.event(message=PRIVATE, nodeid=NODE + "[" + PRIVATE + "]"))), encoding="utf-8")
        destination = self.root / "summary.md"
        console = io.StringIO()
        with patch.dict(os.environ, {"RUNNER_TEMP": str(self.root), "GITHUB_STEP_SUMMARY": str(destination)}), \
                patch.object(ci, "ROOT", self.root), contextlib.redirect_stdout(console):
            self.assertEqual(ci.publish("firefox"), 0)
        self.assertEqual(destination.read_text(encoding="utf-8"), console.getvalue())
        self.assertIn(NODE, console.getvalue())
        self.assertNotIn(CANARY, console.getvalue())
        self.assertNotIn(str(self.root), console.getvalue())

    def test_missing_or_broken_event_log_fails_closed_without_details(self):
        destination = self.root / "summary.md"
        for content in (None, PRIVATE):
            if content:
                (self.root / "qil-e2e-test-events.json").write_text(content, encoding="utf-8")
            console = io.StringIO()
            with patch.dict(os.environ, {"RUNNER_TEMP": str(self.root), "GITHUB_STEP_SUMMARY": str(destination)}), \
                    patch.object(ci, "ROOT", self.root), contextlib.redirect_stdout(console):
                self.assertEqual(ci.publish("webkit"), 0)
            self.assertIn("Failed: 0; Errors: 1", console.getvalue())
            self.assertNotIn(CANARY, console.getvalue())

    def test_summary_cannot_write_outside_private_directory(self):
        outside = self.root.parent / (self.root.name + "-outside.md")
        console = io.StringIO()
        with patch.dict(os.environ, {"RUNNER_TEMP": str(self.root), "GITHUB_STEP_SUMMARY": str(outside)}), patch.object(ci, "ROOT", self.root), contextlib.redirect_stdout(console):
            with self.assertRaises(ValueError):
                ci.publish("webkit")
        self.assertFalse(outside.exists())
        self.assertIn("Browser: webkit", console.getvalue())
        self.assertNotIn(str(outside), console.getvalue())

    def test_run_preserves_failure_exit_code_and_keeps_raw_output_private(self):
        def fake_child(*args, **kwargs):
            self.assertEqual(kwargs["stderr"], subprocess.STDOUT)
            kwargs["stdout"].write(PRIVATE.encode())
            return subprocess.CompletedProcess(args[0], 1)
        destination = self.root / "summary.md"
        console = io.StringIO()
        with patch.dict(os.environ, {"RUNNER_TEMP": str(self.root), "GITHUB_STEP_SUMMARY": str(destination)}), \
                patch.object(ci.subprocess, "run", side_effect=fake_child), contextlib.redirect_stdout(console):
            self.assertEqual(ci.run("webkit"), 1)
        self.assertEqual(console.getvalue(), "")
        self.assertFalse(destination.exists())
        self.assertEqual((self.root / "qil-raw-test.log").read_text(), PRIVATE)

    def test_success_has_no_summary_or_diagnostic_artifact(self):
        destination = self.root / "summary.md"
        with patch.dict(os.environ, {"RUNNER_TEMP": str(self.root), "GITHUB_STEP_SUMMARY": str(destination)}), \
                patch.object(ci.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            self.assertEqual(ci.run("chromium"), 0)
        self.assertFalse(destination.exists())
        self.assertEqual([p.name for p in self.root.iterdir() if p.is_file()], ["qil-raw-test.log"])

    def test_cleanup_removes_only_owned_private_files_after_junit(self):
        for name in ci.PRIVATE_FILES:
            (self.root / name).write_text(PRIVATE, encoding="utf-8")
        sentinel = self.root / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        report = self.root / "qil-safe-report"
        report.mkdir()
        (report / "junit.xml").write_text("<testsuites/>", encoding="utf-8")
        with patch.dict(os.environ, {"RUNNER_TEMP": str(self.root)}):
            self.assertEqual(ci.cleanup(), 0)
            self.assertEqual(ci.cleanup(), 0)
        self.assertTrue(sentinel.is_file())
        self.assertTrue((report / "junit.xml").is_file())
        self.assertTrue(all(not (self.root / name).exists() for name in ci.PRIVATE_FILES))

    def test_cleanup_rejects_symlinks_before_unlinking_anything(self):
        with patch.dict(os.environ, {"RUNNER_TEMP": str(self.root)}), patch.object(Path, "is_symlink", return_value=True), patch.object(Path, "unlink") as unlink:
            with self.assertRaises(ValueError):
                ci.cleanup()
            unlink.assert_not_called()

    def test_invalid_cli_and_internal_errors_never_echo_input_or_traceback(self):
        for args in ([PRIVATE], ["report", PRIVATE], ["run", "webkit", PRIVATE]):
            console = io.StringIO()
            with contextlib.redirect_stdout(console):
                self.assertEqual(ci.main(args), 2)
            self.assertNotIn(CANARY, console.getvalue())
            self.assertNotIn("Traceback", console.getvalue())

    def test_keyboard_interrupt_remains_nonzero_without_a_traceback(self):
        console = io.StringIO()
        with patch.object(ci, "run", side_effect=KeyboardInterrupt), contextlib.redirect_stdout(console):
            self.assertEqual(ci.main(["run", "webkit"]), 130)
        self.assertEqual(console.getvalue(), "")

    def test_unexpected_report_error_has_safe_fields_without_the_error_value(self):
        console = io.StringIO()
        with patch.object(ci, "publish", side_effect=RuntimeError(PRIVATE)), contextlib.redirect_stdout(console):
            self.assertEqual(ci.main(["report", "webkit"]), 2)
        self.assertIn("Browser: webkit", console.getvalue())
        self.assertIn("Failed: 0; Errors: 1", console.getvalue())
        self.assertNotIn(CANARY, console.getvalue())
        self.assertNotIn("Traceback", console.getvalue())

    def test_browser_selection_startup_and_junit_flags_are_preserved(self):
        for browser in ("chromium", "firefox", "webkit"):
            for startup in (False, True):
                with self.subTest(browser=browser, startup=startup), \
                        patch.dict(os.environ, {"RUNNER_TEMP": str(self.root)}), \
                        patch.object(ci, "recorder", return_value=object()), \
                        patch("pytest.main", return_value=1) as execute, patch.object(sys, "path", list(sys.path)):
                    self.assertEqual(ci.child(browser, startup), 1)
                    args = execute.call_args.args[0]
                    self.assertIn("--qil-browser", args)
                    self.assertEqual(args[args.index("--qil-browser") + 1], browser)
                    self.assertIn("--tb=no", args)
                    self.assertIn("--show-capture=no", args)
                    self.assertEqual("--setup-only" in args, startup)
                    self.assertEqual("cross_browser" in args, not startup and browser != "chromium")
                    self.assertEqual(any(arg.startswith("--junitxml=") for arg in args), not startup)

    def test_real_pytest_recorder_never_serializes_failure_message(self):
        source = self.root / SOURCE
        source.write_text("import pytest\n@pytest.mark.parametrize('value', [0], ids=['" + PRIVATE + "::tail'])\ndef test_answer(value):\n    assert False, '" + PRIVATE + "'\n\ndef test_timeout():\n    raise TimeoutError('" + PRIVATE + "')\n", encoding="utf-8")
        (self.root / "pytest.ini").write_text("[pytest]\naddopts = -p no:django\n", encoding="utf-8")
        events = self.root / "events.json"
        script = "import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import pytest;from tools.playwright_ci import recorder;raise SystemExit(pytest.main(['-c','pytest.ini','tests/e2e/test_probe.py','-q','--tb=no','--show-capture=no','--no-summary'],plugins=[recorder(Path.cwd(),Path('events.json'))]))"
        result = subprocess.run([sys.executable, "-B", "-c", script, str(ci.ROOT)], cwd=self.root,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        self.assertEqual(result.returncode, 1)
        registry = ci.Registry(self.root)
        summary = ci.render("webkit", ci.read_events(events, registry))
        self.assertIn("Failed: 2; Errors: 0", summary)
        self.assertIn("AssertionError", summary)
        self.assertIn("TimeoutError", summary)
        self.assertIn(SOURCE + ":4", summary)
        self.assertIn(SOURCE + ":7", summary)
        self.assertNotIn(CANARY, summary)
        self.assertNotIn(CANARY, events.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
