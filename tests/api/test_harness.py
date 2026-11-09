import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from . import harness


@pytest.fixture
def spawned_processes(monkeypatch):
    processes = []
    popen = subprocess.Popen

    def track(command, **kwargs):
        process = popen(command, **kwargs)
        processes.append((process, Path(command[-1])))
        return process

    monkeypatch.setattr(harness.subprocess, "Popen", track)
    return processes


def test_reports_unlaunchable_backend(tmp_path):
    with pytest.raises(harness.BackendError, match="Could not launch backend"):
        with harness.backend_http([str(tmp_path / "missing-python.exe")], cwd=tmp_path):
            pytest.fail("Backend unexpectedly started")


def test_reports_backend_exit_before_readiness(tmp_path):
    command = [sys.executable, "-B", "-c", "raise SystemExit(23)"]
    with pytest.raises(harness.BackendError, match="exit=23"):
        with harness.backend_http(command, cwd=tmp_path):
            pytest.fail("Backend unexpectedly started")


def test_backend_refuses_a_development_database(tmp_path):
    command = [sys.executable, "-B", str(Path(harness.__file__)), "qa_interview_lab"]
    with pytest.raises(harness.BackendError, match=r"Backend startup failed \(BackendError\)"):
        with harness.backend_http(command, cwd=tmp_path):
            pytest.fail("Backend unexpectedly started")


def test_terminates_child_when_startup_times_out(tmp_path, spawned_processes):
    command = [sys.executable, "-B", "-c", "import time; time.sleep(120)"]
    with pytest.raises(harness.BackendError, match="startup timed out"):
        with harness.backend_http(command, cwd=tmp_path, startup_timeout=0.2):
            pytest.fail("Backend unexpectedly started")

    [(process, ready_file)] = spawned_processes
    assert process.poll() is not None
    assert not ready_file.parent.exists()


def test_closes_client_and_child_after_test_failure(tmp_path, monkeypatch, spawned_processes):
    child = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "ready = Path(sys.argv[1])\n"
        "pending = ready.with_suffix('.tmp')\n"
        "pending.write_text('49152', encoding='ascii')\n"
        "pending.replace(ready)\n"
        "time.sleep(120)\n"
    )
    monkeypatch.setattr(harness, "_wait_for_http", lambda *args: None)
    with pytest.raises(ValueError, match="synthetic test failure"):
        with harness.backend_http([sys.executable, "-B", "-c", child], cwd=tmp_path) as (client, process):
            assert process.poll() is None
            raise ValueError("synthetic test failure")

    assert client.is_closed
    assert process.poll() is not None
    assert not spawned_processes[0][1].parent.exists()


@pytest.mark.parametrize(
    ("error", "detail"),
    [
        (httpx.ConnectError, "loopback port unavailable"),
        (httpx.ReadTimeout, "HTTP request timed out"),
    ],
)
def test_reports_readiness_timeout(error, detail):
    def unavailable(request):
        raise error("synthetic connection failure", request=request)

    with httpx.Client(
        base_url="http://127.0.0.1:49152", transport=httpx.MockTransport(unavailable)
    ) as client:
        with pytest.raises(harness.BackendError, match=detail):
            harness._wait_for_http(client, SimpleNamespace(poll=lambda: None), time.monotonic() + 0.2)


def test_rejects_an_invalid_http_response():
    def malformed(request):
        raise httpx.RemoteProtocolError("synthetic malformed HTTP", request=request)

    with httpx.Client(
        base_url="http://127.0.0.1:49152", transport=httpx.MockTransport(malformed)
    ) as client:
        with pytest.raises(harness.BackendError, match="invalid HTTP response"):
            harness._wait_for_http(client, SimpleNamespace(poll=lambda: None), time.monotonic() + 1)
