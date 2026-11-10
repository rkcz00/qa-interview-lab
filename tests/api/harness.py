import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx


LOOPBACK = "127.0.0.1"
STARTUP_TIMEOUT = 15.0
REQUEST_TIMEOUT = 3.0
SHUTDOWN_TIMEOUT = 5.0
POLL_INTERVAL = 0.05


class BackendError(RuntimeError):
    pass


def _require_running(process):
    code = process.poll()
    if code is not None:
        raise BackendError(f"Backend exited before readiness (exit={code})")


def _wait_for_port(process, ready_file, deadline):
    while time.monotonic() < deadline:
        if ready_file.is_file():
            status = ready_file.read_text(encoding="ascii", errors="replace").strip()
            if re.fullmatch(r"error [A-Za-z_][A-Za-z0-9_]*(?: [0-9]+)?", status):
                raise BackendError(f"Backend startup failed ({status[6:]})")
            _require_running(process)
            if re.fullmatch(r"[0-9]{1,5}", status) and 0 < int(status) <= 65535:
                return int(status)
            raise BackendError("Backend reported an invalid loopback port")
        _require_running(process)
        time.sleep(POLL_INTERVAL)
    raise BackendError("Backend startup timed out before publishing a loopback port")


def _wait_for_http(client, process, deadline):
    pending = "no HTTP response"
    while (remaining := deadline - time.monotonic()) > 0:
        _require_running(process)
        try:
            response = client.get("/", timeout=min(REQUEST_TIMEOUT, remaining))
        except httpx.ConnectError:
            pending = "loopback port unavailable"
        except httpx.TimeoutException:
            pending = "HTTP request timed out"
        except httpx.RequestError:
            raise BackendError("Backend returned an invalid HTTP response") from None
        else:
            if response.status_code != 200:
                raise BackendError(f"Backend readiness expected HTTP 200, got {response.status_code}")
            return
        time.sleep(min(POLL_INTERVAL, max(0, deadline - time.monotonic())))
    raise BackendError(f"Backend readiness timed out ({pending})")


@contextmanager
def backend_http(command, *, cwd, env=None, startup_timeout=STARTUP_TIMEOUT):
    """Run one child process that publishes its listening port to a private file."""
    with TemporaryDirectory(prefix="qil006-http-") as directory:
        ready_file = Path(directory) / "ready"
        deadline = time.monotonic() + startup_timeout
        try:
            process = subprocess.Popen(
                [*command, str(ready_file)],
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise BackendError(f"Could not launch backend ({type(exc).__name__})") from None

        try:
            port = _wait_for_port(process, ready_file, deadline)
            with httpx.Client(
                base_url=f"http://{LOOPBACK}:{port}", timeout=REQUEST_TIMEOUT, trust_env=False
            ) as client:
                _wait_for_http(client, process, deadline)
                yield client, process
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=SHUTDOWN_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=SHUTDOWN_TIMEOUT)


def _publish_status(ready_file, status):
    pending = ready_file.with_suffix(".tmp")
    pending.write_text(status, encoding="ascii")
    pending.replace(ready_file)


def _serve_django(database, ready_file):
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIServer, make_server

    class ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    try:
        if not re.fullmatch(r"test_qil006_[0-9a-f]{32}", database):
            raise BackendError("Expected a disposable QIL PostgreSQL database")
        if os.environ.get("POSTGRES_DB") != database:
            raise BackendError("Unexpected database environment")

        sys.path.insert(0, str(Path.cwd()))
        from config.wsgi import application
        from django.db import connection

        if connection.vendor != "postgresql" or connection.settings_dict["NAME"] != database:
            raise BackendError("Unexpected Django database")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            if cursor.fetchone()[0] != database:
                raise BackendError("PostgreSQL connected to an unexpected database")
        connection.close()

        # The OS selects and holds the port in this single, non-reloading process.
        with make_server(LOOPBACK, 0, application, server_class=ThreadedWSGIServer) as server:
            _publish_status(ready_file, str(server.server_port))
            server.serve_forever()
    except Exception as exc:
        code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
        kind = type(exc).__name__
        _publish_status(ready_file, f"error {kind} {code}" if isinstance(code, int) else f"error {kind}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_serve_django(sys.argv[1], Path(sys.argv[2])))
