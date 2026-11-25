"""Private pytest execution and an allowlisted, message-free CI failure summary."""

import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
BROWSERS = {"chromium", "firefox", "webkit"}
EXCEPTIONS = {
    "AssertionError", "TimeoutError", "Exception", "Error", "Failed", "RuntimeError",
    "ValueError", "TypeError", "OSError", "PermissionError", "FileNotFoundError",
    "ConnectionError", "ImportError", "ModuleNotFoundError", "SyntaxError",
    "SystemExit", "KeyboardInterrupt", "UsageError", "BackendError", "DatabaseError",
    "OperationalError", "IntegrityError",
}
PRIVATE_FILES = (
    "qil-e2e-startup.log", "qil-raw-test.log", "qil-raw-junit.xml",
    "qil-e2e-startup-events.json", "qil-e2e-test-events.json",
)
MAX_INPUT = 1_000_000
MAX_EVENTS = 10_000
SOURCE = re.compile(r"tests/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*\.py")


class Registry:
    """Only names and locations that actually exist in the checked-out tests."""

    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        self.nodes = set()
        self.lines = {}
        for path in sorted((self.root / "tests").rglob("*.py")):
            relative = path.relative_to(self.root).as_posix()
            if path.is_symlink() or not SOURCE.fullmatch(relative):
                continue
            if not path.resolve().is_relative_to(self.root):
                continue
            source = path.read_text(encoding="utf-8-sig")
            self.lines[relative] = len(source.splitlines())
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue  # Collection errors still have counts, without invented test IDs.
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                    self.nodes.add(relative + "::" + node.name)

    def relative(self, path):
        try:
            relative = Path(path).resolve().relative_to(self.root).as_posix()
        except (OSError, ValueError):
            return None
        return relative if relative in self.lines else None

    def node(self, value):
        # Parametrization may contain credentials or arbitrary text: never publish it.
        if not isinstance(value, str):
            return None
        stable = value.split("[", 1)[0]
        return stable if stable in self.nodes else None

    def location(self, path, line):
        if not isinstance(path, str) or path not in self.lines or type(line) is not int:
            return None
        if not 1 <= line <= self.lines[path]:
            return None
        return f"{path}:{line}"


def sanitize(document, registry):
    """Project structured failure events; ignore messages, values and all extra keys."""
    if not isinstance(document, dict) or type(document.get("version")) is not int or document.get("version") != 1 or document.get("complete") is not True:
        raise ValueError("Invalid private event log")
    events = document.get("events")
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError("Invalid private event log")
    failed = errors = 0
    rows = []
    for event in events:
        if not isinstance(event, dict) or event.get("phase") not in {"call", "setup", "teardown", "collect", "internal"}:
            raise ValueError("Invalid private event log")
        if event["phase"] == "call":
            failed += 1
        else:
            errors += 1
        node = registry.node(event.get("nodeid"))
        location = registry.location(event.get("path"), event.get("line"))
        kind = event.get("exception_type")
        if not isinstance(kind, str) or kind not in EXCEPTIONS:
            kind = "Exception"
        if node and location:
            row = (node, kind, location)
            if row not in rows:
                rows.append(row)
    return {"failed": failed, "errors": errors, "rows": rows}


def read_events(path, registry):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT:
        raise ValueError("Invalid private event log")
    return sanitize(json.loads(path.read_text(encoding="utf-8")), registry)


def render(browser, report):
    if browser not in BROWSERS:
        raise ValueError("Invalid browser")
    lines = ["## Playwright failure summary", "", f"Browser: {browser}",
             f"Failed: {report['failed']}; Errors: {report['errors']}", "",
             "| Test | Exception | Source |", "| --- | --- | --- |"]
    for node, kind, location in report["rows"]:
        lines.append(f"| `{node}` | `{kind}` | `{location}` |")
    if not report["rows"]:
        lines.extend(["", "Failure details unavailable."])
    return "\n".join(lines) + "\n"


def recorder(root, event_path):
    """The pytest dependency is needed by the child only, never by the sanitizer."""
    import pytest

    class Recorder:
        def __init__(self):
            self.registry = Registry(root)
            self.events = []

        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_makereport(self, item, call):
            outcome = yield
            report = outcome.get_result()
            if not report.failed:
                return
            path = self.registry.relative(item.path)
            name = item.nodeid.split("[", 1)[0].rsplit("::", 1)[-1]
            event = {"nodeid": f"{path}::{name}", "phase": report.when,
                     "exception_type": call.excinfo.typename if call.excinfo else "Exception"}
            candidates = []
            if call.excinfo:
                for frame in call.excinfo.traceback:
                    relative = self.registry.relative(str(frame.path))
                    if relative:
                        candidates.append((relative, frame.lineno + 1, frame.name))
            preferred = [frame for frame in candidates if frame[0] == path and frame[2] == name]
            if preferred or candidates:
                source, line, _ = (preferred or candidates)[-1]
                event.update(path=source, line=line)
            self.events.append(event)

        def pytest_collectreport(self, report):
            if report.failed:
                self.events.append({"phase": "collect"})

        def pytest_internalerror(self, excrepr, excinfo):
            self.events.append({"phase": "internal"})

        def pytest_sessionfinish(self, session, exitstatus):
            with event_path.open("x", encoding="utf-8") as stream:
                json.dump({"version": 1, "complete": True, "events": self.events}, stream)

    return Recorder()


def temporary_root():
    root = Path(os.environ["RUNNER_TEMP"])
    if root.is_symlink() or not root.is_absolute() or not root.is_dir():
        raise ValueError("Invalid private directory")
    return root.resolve(strict=True)


def run(browser, startup=False):
    root = temporary_root()
    event = root / ("qil-e2e-startup-events.json" if startup else "qil-e2e-test-events.json")
    log = root / ("qil-e2e-startup.log" if startup else "qil-raw-test.log")
    junit = root / "qil-raw-junit.xml"
    if any(path.exists() or path.is_symlink() for path in (event, log)) or (not startup and (junit.exists() or junit.is_symlink())):
        raise ValueError("Private file already exists")
    with log.open("xb") as stream:
        result = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "child", browser, "startup" if startup else "tests"],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
        )
    return result.returncode


def child(browser, startup):
    import pytest

    root = temporary_root()
    event = root / ("qil-e2e-startup-events.json" if startup else "qil-e2e-test-events.json")
    args = ["-c", "tests/e2e/pytest.ini"]
    if startup:
        args += ["tests/e2e/test_auth_ui.py::test_direct_routes_guest_restore_and_home", "--setup-only"]
    else:
        args += ["tests/e2e"]
        if browser != "chromium":
            args += ["-m", "cross_browser"]
        args += ["-o", "junit_logging=no", "-o", "junit_log_passing_tests=false", "--junitxml=" + str(root / "qil-raw-junit.xml")]
    args += ["--qil-browser", browser, "-q", "--tb=no", "--show-capture=no", "--no-summary"]
    sys.path.insert(0, str(ROOT))
    return int(pytest.main(args, plugins=[recorder(ROOT, event)]))


def publish(browser):
    root = temporary_root()
    registry = Registry(ROOT)
    combined = {"failed": 0, "errors": 0, "rows": []}
    for name in ("qil-e2e-startup-events.json", "qil-e2e-test-events.json"):
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue
        try:
            report = read_events(path, registry)
        except (OSError, ValueError, TypeError, RecursionError):
            report = {"failed": 0, "errors": 1, "rows": []}
        combined["failed"] += report["failed"]
        combined["errors"] += report["errors"]
        combined["rows"].extend(row for row in report["rows"] if row not in combined["rows"])
    if not combined["failed"] and not combined["errors"]:
        combined["errors"] = 1  # A failed setup/install/runner may have no pytest event.
    summary = render(browser, combined)
    print(summary, end="")  # Even a Step Summary write error cannot hide safe console fields.
    destination = os.environ.get("GITHUB_STEP_SUMMARY")
    if destination:
        path = Path(destination)
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Invalid summary destination")
        with path.open("a", encoding="utf-8") as stream:
            stream.write(summary)
    return 0


def cleanup():
    root = temporary_root()
    paths = [root / name for name in PRIVATE_FILES]
    if any(path.is_symlink() or (path.exists() and not path.is_file()) for path in paths):
        raise ValueError("Invalid private file")
    for path in paths:
        path.unlink(missing_ok=True)
    return 0


def main(args):
    # Never let argument errors or exception formatting echo paths or user values.
    try:
        if args == ["cleanup"]:
            return cleanup()
        if len(args) not in (2, 3) or args[1] not in BROWSERS:
            raise ValueError("Invalid arguments")
        command, browser = args[:2]
        if command == "report" and len(args) == 2:
            return publish(browser)
        if command in {"run", "child"} and (len(args) == 2 or args[2] in {"startup", "tests"}):
            startup = len(args) == 3 and args[2] == "startup"
            return run(browser, startup) if command == "run" else child(browser, startup)
        raise ValueError("Invalid arguments")
    except KeyboardInterrupt:
        return 130
    except Exception:
        # This is an output boundary, not a conversion of application failures to success.
        if len(args) == 2 and args[0] == "report" and args[1] in BROWSERS:
            print(render(args[1], {"failed": 0, "errors": 1, "rows": []}), end="")
        else:
            print("Safe Playwright diagnostics unavailable.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
