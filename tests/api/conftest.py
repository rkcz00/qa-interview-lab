import os
import sys
from pathlib import Path
from secrets import token_urlsafe

import pytest
from django.db import connection

from .harness import backend_http


@pytest.fixture
def api_client(transactional_db, django_db_modify_db_settings, settings):
    """Serve committed test fixtures over TCP, then stop the server before DB cleanup."""
    database = django_db_modify_db_settings
    if connection.settings_dict["NAME"] != database:
        pytest.fail("Backend must use the active pytest PostgreSQL database", pytrace=False)

    # Session fixtures and the backend use the same synthetic signing key.
    settings.SECRET_KEY = token_urlsafe(32)
    env = dict(
        os.environ,
        DJANGO_SETTINGS_MODULE="config.settings",
        DJANGO_SECRET_KEY=settings.SECRET_KEY,
        DJANGO_ALLOWED_HOSTS="127.0.0.1",
        DJANGO_DEBUG="true",  # Use the documented local cookie settings on loopback HTTP.
        POSTGRES_DB=database,
        POSTGRES_TEST_DB=f"{database}_unused",
    )
    backend = Path(__file__).resolve().parents[2] / "backend"
    command = [sys.executable, "-B", str(Path(__file__).with_name("harness.py")), database]
    with backend_http(command, cwd=backend, env=env) as (client, _):
        yield client
