from time import monotonic, sleep

import pytest
from django.db import connection


def wait_for_lock_waiters(table, expected_count):
    deadline = monotonic() + 5
    with connection.cursor() as cursor:
        while monotonic() < deadline:
            cursor.execute("SELECT pg_stat_clear_snapshot()")
            cursor.execute(
                """
                SELECT count(*) FROM pg_stat_activity
                WHERE datname = current_database() AND pid <> pg_backend_pid()
                  AND wait_event_type = 'Lock' AND query LIKE %s
                """,
                (f"%{table}%FOR UPDATE%",),
            )
            if cursor.fetchone()[0] == expected_count:
                return
            sleep(0.025)
    pytest.fail(f"Expected {expected_count} HTTP requests waiting on the {table} lock", pytrace=False)
