"""Run QIL-029 locally without logging credentials or touching the development DB."""

import hashlib
import importlib.util
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
OLD_HELPERS = (
    "check-django-admin.py", "check-httpx-harness.py", "check-postgres-restart.py",
    "check-progress.py", "check-registration.py", "check-session.py",
)
PROGRESS_INTERVAL = 30


class CheckFailed(RuntimeError):
    pass


def project_python():
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        raise CheckFailed("PROJECT_VENV=BLOCKED missing project interpreter")
    if Path(sys.executable).resolve() != python.resolve():
        print("PYTHON_ENV=SWITCHING_TO_PROJECT_VENV", flush=True)
        # Only the checked project interpreter and this fixed script are executed.
        # Windows execv returns the original console prompt before the replacement
        # process finishes. Keep the parent waiting for the checked interpreter.
        child = subprocess.Popen([str(python), "-B", str(Path(__file__).resolve()), *sys.argv[1:]])
        try:
            status = child.wait()
        except KeyboardInterrupt:
            # The child receives the same console interrupt; allow its cleanup to finish.
            try:
                status = child.wait(timeout=45)
            except subprocess.TimeoutExpired:
                print("PROJECT_VENV=CLEANUP_PENDING child still running; cleanup is not confirmed", flush=True)
                status = 130
        raise SystemExit(status)
    print("PYTHON_ENV=PROJECT_VENV", flush=True)


def file_hashes():
    paths = set()
    for arguments in (("ls-files", "-z"), ("ls-files", "--others", "--exclude-standard", "-z")):
        result = subprocess.run(["git", "-C", str(ROOT), *arguments], check=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        paths.update(result.stdout.decode("utf-8").split("\0"))
    paths.update((".env", *OLD_HELPERS))
    return {name: hashlib.sha256((ROOT / name).read_bytes()).digest()
            for name in paths if name and (ROOT / name).is_file()}


def load_environment():
    env = dict(os.environ)
    path = ROOT / ".env"
    if not path.is_file():
        raise CheckFailed("ENV=BLOCKED existing local .env is required; nothing was created")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = line.partition("=")
        key = key.strip()
        if separator and key and not key.startswith("#"):
            # Use the existing project's credentials, without printing or rotating them.
            env[key] = value.strip().strip('"').strip("'")
    if any(not env.get(key) for key in ("POSTGRES_PASSWORD", "POSTGRES_USER", "POSTGRES_HOST", "POSTGRES_PORT")):
        raise CheckFailed("ENV=BLOCKED required database keys are missing; values hidden")
    if env["POSTGRES_HOST"] not in {"localhost", "127.0.0.1", "::1"}:
        raise CheckFailed("POSTGRES=BLOCKED only loopback is allowed")
    return env


def stop_owned_process_tree(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    else:
        import signal
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def run_check(name, command, env, *, cwd=ROOT, timeout=900):
    print(f"{name}=RUNNING", flush=True)
    options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
               else {"start_new_session": True})
    process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **options)
    started = time.monotonic()
    deadline = started + timeout
    try:
        while True:
            try:
                output, _ = process.communicate(timeout=min(PROGRESS_INTERVAL, max(0.01, deadline - time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise
                print(f"{name}=RUNNING elapsed={int(time.monotonic() - started)}s", flush=True)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        stop_owned_process_tree(process)
        raise CheckFailed(f"{name}=FAIL interrupted/timeout; owned process tree stopped") from None
    finally:
        stop_owned_process_tree(process)
    text = output.decode("utf-8", errors="replace")
    if process.returncode:
        # Do not echo pytest assertions, SQL, request bodies or exception values.
        failed = sorted(set(re.findall(r"FAILED [^\n]*::([A-Za-z_][A-Za-z_0-9]*)", text)))
        for function in failed:
            print("FAILED_TEST=" + function, flush=True)
        raise CheckFailed(f"{name}=FAIL exit={process.returncode}; private diagnostics suppressed")
    counts = re.findall(r"\b\d+ (?:passed|subtests passed|skipped|deselected)\b", text)
    if name == "FRONTEND_UNIT":
        counts += ["tests=" + count for count in re.findall(r"(?:ℹ|#) tests (\d+)", text)]
    print(f"{name}=PASS" + (" " + ", ".join(counts[-5:]) if counts else ""), flush=True)


def main():
    project_python()
    if not all((ROOT / name).is_file() for name in ("AGENTS.md", "README.md", "compose.yaml", "docs/PRACTICE_SPEC.md")):
        raise CheckFailed("PROJECT=BLOCKED unexpected project root")
    for module in ("django", "pytest", "pytest_django", "psycopg", "httpx", "playwright"):
        if importlib.util.find_spec(module) is None:
            raise CheckFailed("DEPENDENCIES=BLOCKED missing project QA package; no installation performed")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm or not (ROOT / "frontend/node_modules").is_dir():
        raise CheckFailed("FRONTEND=BLOCKED existing npm and frontend/node_modules are required")
    before = file_hashes()
    env = load_environment()
    import psycopg
    from psycopg import sql
    try:
        maintenance = psycopg.connect(dbname="postgres", user=env["POSTGRES_USER"], password=env["POSTGRES_PASSWORD"],
                                     host=env["POSTGRES_HOST"], port=env["POSTGRES_PORT"], connect_timeout=3, autocommit=True)
    except psycopg.Error:
        raise CheckFailed("POSTGRES=BLOCKED connection failed; start the existing postgres service manually") from None
    database = "test_qil006_" + uuid4().hex
    created = False
    cleanup_ok = True
    tests_ok = False
    try:
        if maintenance.execute("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname=%s)", (database,)).fetchone()[0]:
            raise CheckFailed("TEMP_DATABASE=BLOCKED refusing an existing database")
        maintenance.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        created = True
        print("TEMP_POSTGRES=PASS new isolated database", flush=True)
        env.update(DJANGO_SETTINGS_MODULE="config.settings", DJANGO_SECRET_KEY=secrets.token_urlsafe(48),
                   DJANGO_DEBUG="true", DJANGO_ALLOWED_HOSTS="127.0.0.1,localhost", POSTGRES_DB=database,
                   POSTGRES_TEST_DB="unused_" + uuid4().hex, PYTHONDONTWRITEBYTECODE="1")
        browsers = ROOT / ".venv/ms-playwright"
        if browsers.is_dir():
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)
        python = [sys.executable, "-B"]
        manage = [*python, str(ROOT / "backend/manage.py")]
        run_check("MIGRATE_TEMP", [*manage, "migrate", "--noinput"], env)
        run_check("DJANGO_CHECK", [*manage, "check"], env)
        run_check("MIGRATION_FILES", [*manage, "makemigrations", "--check", "--dry-run"], env)
        run_check("MIGRATE_CHECK", [*manage, "migrate", "--check"], env)
        run_check("PIP_CHECK", [*python, "-m", "pip", "check"], env)
        run_check("BACKEND_REGRESSION", [*python, "-m", "pytest", "-q", "--tb=no", "--show-capture=no"], env)
        frontend_env = {key: value for key, value in env.items() if not key.startswith(("POSTGRES_", "DJANGO_", "VITE_"))}
        frontend_env["CI"] = "true"
        run_check("FRONTEND_UNIT", [npm, "test"], frontend_env, cwd=ROOT / "frontend")
        run_check("FRONTEND_TYPECHECK", [npm, "run", "typecheck"], frontend_env, cwd=ROOT / "frontend")
        run_check("FRONTEND_BUILD", [npm, "run", "build"], frontend_env, cwd=ROOT / "frontend")
        run_check("PLAYWRIGHT_REGRESSION", [*python, "-m", "pytest", "-c", "tests/e2e/pytest.ini",
                  "tests/e2e", "-q", "--tb=no", "--show-capture=no"], env, timeout=1500)
        tests_ok = True
    finally:
        try:
            if created:
                assert re.fullmatch(r"test_qil006_[0-9a-f]{32}", database)
                maintenance.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
                if maintenance.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone():
                    raise CheckFailed("TEMP_CLEANUP=FAIL disposable database remains")
                print("TEMP_CLEANUP=PASS runner database removed; harness owns child databases/processes", flush=True)
        except psycopg.Error:
            cleanup_ok = False
            print("TEMP_CLEANUP=FAIL; private database diagnostics suppressed", flush=True)
        finally:
            maintenance.close()
            if file_hashes() != before:
                raise CheckFailed("FILES=FAIL project or protected files changed during checks")
            print("FILES=PASS .env, source and old helpers unchanged", flush=True)
    if not tests_ok or not cleanup_ok:
        raise CheckFailed("RESULT=FAIL verification or cleanup incomplete")
    print("RESULT=PASS", flush=True)


if __name__ == "__main__":
    try:
        main()
    except CheckFailed as error:
        print(str(error), flush=True)
        print("RESULT=FAIL", flush=True)
        raise SystemExit(1)
    except Exception as error:
        print("CHECK=FAIL exception=" + type(error).__name__ + "; private details suppressed", flush=True)
        print("RESULT=FAIL", flush=True)
        raise SystemExit(1)
