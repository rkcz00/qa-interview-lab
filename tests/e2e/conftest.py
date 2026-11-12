"""Real Auth UI: one disposable PostgreSQL database and two owned loopback processes."""

import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.api.harness import backend_http


@pytest.fixture(scope="session")
def auth_app():
    if not (ROOT / "frontend/dist/index.html").is_file():
        pytest.fail("Build frontend before Auth E2E", pytrace=False)
    node = shutil.which("node")
    if not node or not os.environ.get("POSTGRES_PASSWORD"):
        pytest.fail("Auth E2E requires Node.js and process-local PostgreSQL credentials", pytrace=False)
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Auth E2E only uses loopback PostgreSQL", pytrace=False)
    database = "test_qil006_" + uuid4().hex
    connection_options = {
        "host": host, "port": os.environ.get("POSTGRES_PORT", "5432"),
        "user": os.environ.get("POSTGRES_USER", "qil"),
        "password": os.environ["POSTGRES_PASSWORD"], "connect_timeout": 3,
    }
    try:
        maintenance = psycopg.connect(dbname="postgres", autocommit=True, **connection_options)
    except psycopg.Error:
        pytest.fail("Auth E2E PostgreSQL connection failed; credentials were not logged", pytrace=False)
    created = False
    processes = []
    try:
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        created = True
        backend_env = dict(os.environ, DJANGO_SETTINGS_MODULE="config.settings", DJANGO_DEBUG="true",
            DJANGO_ALLOWED_HOSTS="127.0.0.1,localhost", DJANGO_SECRET_KEY=secrets.token_urlsafe(48),
            POSTGRES_DB=database, POSTGRES_TEST_DB="unused_" + uuid4().hex,
            POSTGRES_HOST=host, PYTHONDONTWRITEBYTECODE="1")
        migrated = subprocess.run([sys.executable, "-B", str(ROOT / "backend/manage.py"), "migrate", "--noinput"],
            cwd=ROOT, env=backend_env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=60)
        if migrated.returncode:
            pytest.fail("Auth E2E disposable database migration failed", pytrace=False)
        owned_topics = set()

        def learning_data(action, topic_ids=()):
            if action != "create" and (not topic_ids or not set(topic_ids).issubset(owned_topics)):
                pytest.fail("Learning E2E may change only topics created by this fixture", pytrace=False)
            result = subprocess.run([sys.executable, "-B", str(ROOT / "tests/e2e/learning_data.py"),
                database, action, *topic_ids], cwd=ROOT, env=backend_env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            if result.returncode:
                pytest.fail("Learning E2E fixture operation failed; credentials were not logged", pytrace=False)
            data = json.loads(result.stdout)
            if action == "create":
                owned_topics.update(data["ids"])
            if action == "cleanup":
                owned_topics.difference_update(topic_ids)
            return data

        with backend_http([sys.executable, "-B", str(ROOT / "tests/api/harness.py"), database],
                cwd=ROOT / "backend", env=backend_env) as (backend, backend_process):
            processes.append(backend_process)
            # Vite only needs the public proxy address, never database or Django secrets.
            frontend_env = {key: value for key, value in os.environ.items()
                if not key.startswith(("POSTGRES_", "DJANGO_", "VITE_"))}
            frontend_env["QIL_API_PROXY_TARGET"] = str(backend.base_url).rstrip("/")
            with backend_http([node, str(ROOT / "frontend/tests/preview-server.mjs")],
                    cwd=ROOT / "frontend", env=frontend_env) as (frontend, frontend_process):
                processes.append(frontend_process)
                yield SimpleNamespace(url=str(frontend.base_url).rstrip("/"), learning_data=learning_data)
    finally:
        try:
            if created:
                # Only this fixture's randomly named database may be removed.
                with maintenance.cursor() as cursor:
                    cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
                    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
                    if cursor.fetchone() is not None:
                        pytest.fail("Auth E2E database cleanup failed", pytrace=False)
            if any(process.poll() is None for process in processes):
                pytest.fail("Auth E2E process cleanup failed", pytrace=False)
            print("AUTH_E2E_CLEANUP=PASS database and owned processes")
        finally:
            maintenance.close()


@pytest.fixture
def auth_browser(auth_app):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def auth_page(auth_app, auth_browser):
    # No traces, HAR, video or persisted authentication state: these contain tokens.
    context = auth_browser.new_context(base_url=auth_app.url, locale="ru-RU")
    page = context.new_page()
    page.set_default_timeout(8_000)
    try:
        yield page
    finally:
        context.close()


@pytest.fixture
def learning_topics(auth_app):
    data = auth_app.learning_data("create")
    try:
        yield data
    finally:
        auth_app.learning_data("cleanup", data["ids"])
