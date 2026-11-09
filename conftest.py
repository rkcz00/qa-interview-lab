from uuid import uuid4

import psycopg
import pytest
from django.db import connections
from psycopg import sql


def database_exists(catalog, name):
    return catalog.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)", (name,)
    ).fetchone()[0]


@pytest.fixture(scope="session")
def django_db_modify_db_settings(request):
    """Give pytest-django a disposable PostgreSQL database for this session."""
    if request.config.getoption("reuse_db"):
        pytest.fail("Use a fresh database for QIL tests (omit --reuse-db)", pytrace=False)

    connection = connections["default"]
    config = connection.settings_dict
    if connection.vendor != "postgresql" or config["NAME"] == "postgres":
        pytest.fail("QIL tests require PostgreSQL and a separate maintenance database", pytrace=False)

    name = f"test_qil006_{uuid4().hex}"
    params = {**connection.get_connection_params(), "dbname": "postgres"}
    with psycopg.connect(**params, autocommit=True) as catalog:
        if name == config["NAME"] or database_exists(catalog, name):
            pytest.fail("Refusing to use an existing database for tests", pytrace=False)

        with pytest.MonkeyPatch.context() as patch:
            # Keep Django's maintenance-connection fallback away from the development database.
            patch.setitem(config, "NAME", name)
            patch.setitem(config["TEST"], "NAME", name)
            yield name

        if database_exists(catalog, name):
            # Recover only the database reserved for this run if setup or teardown failed.
            connection.close()
            catalog.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
            pytest.fail("pytest-django left the test database behind; recovery removed it", pytrace=False)
