"""Verified, synthetic legacy transition in a new owning E2E PostgreSQL only."""
import contextlib
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile


def prepare(database):
    if not re.fullmatch(r"test_qil006_[0-9a-f]{32}", database) or os.environ.get("POSTGRES_DB") != database:
        raise RuntimeError("Expected the owning temporary database")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    import django
    django.setup()
    from django.apps import apps
    from django.core.management import call_command
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from django.db.migrations.recorder import MigrationRecorder
    from apps.assessments.section_provenance_v1 import SectionProvenanceRequired

    if connection.settings_dict["NAME"] != database:
        raise RuntimeError("Unexpected database")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        if cursor.fetchone()[0] != database:
            raise RuntimeError("Unexpected PostgreSQL connection")
    if connection.introspection.table_names():
        raise RuntimeError("Verified fixture requires a newly created empty database")
    before = [("learning", "0002_topic_revision"), ("assessments", "0004_user_progress_state")]
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    executor.migrate(before)
    old = executor.loader.project_state(before).apps
    topic = old.get_model("learning", "Topic").objects.create(status="draft")
    for language in ("ru", "en"):
        old.get_model("learning", "TopicTranslation").objects.create(
            topic_id=topic.pk, language=language, title=language + " synthetic legacy", article_body=language + " original body",
        )
    user = old.get_model("accounts", "User").objects.create(email="verified-fixture@example.invalid", password="!")
    first = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    old.get_model("assessments", "TopicProgress").objects.create(user_id=user.pk, topic_id=topic.pk, article_read_at=first)
    content_target = [("learning", "0003_topic_sections"), ("assessments", "0004_user_progress_state")]
    MigrationExecutor(connection).migrate(content_target)
    state = MigrationExecutor(connection).loader.project_state(content_target).apps
    # This is a controlled transition: record its output immediately, before edits.
    original = state.get_model("learning", "TopicSection").objects.get(topic_id=topic.pk)
    applied = MigrationRecorder(connection).migration_qs.get(app="learning", name="0003_topic_sections").applied
    names = ("QIL_SECTION_PROVENANCE_FILE", "QIL_SECTION_PROVENANCE_SHA256")
    previous = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ.pop(name, None)
        try:
            MigrationExecutor(connection).migrate(latest)
        except SectionProvenanceRequired:
            pass
        else:
            raise RuntimeError("Migration guard did not reject missing provenance")
        if "assessments_topicsectionprogress" in connection.introspection.table_names():
            raise RuntimeError("Failed provenance migration did not roll back")
        with tempfile.TemporaryDirectory(prefix="qil-verified-origin-") as directory:
            path = Path(directory) / "synthetic-origins.json"
            content = json.dumps({"version": 1, "source_migration": "learning.0003_topic_sections",
                "applied_at": applied.isoformat(), "origins": [{"topic_id": str(topic.pk), "section_id": str(original.pk)}]}).encode()
            path.write_bytes(content)
            os.environ[names[0]] = str(path)
            os.environ[names[1]] = hashlib.sha256(content).hexdigest()
            call_command("check_section_provenance", verbosity=0)
            call_command("migrate", interactive=False, verbosity=0)
            marks = apps.get_model("assessments", "TopicSectionProgress")
            mark = marks.objects.get(user_id=user.pk, section_id=original.pk)
            if mark.read_at != first or marks.objects.count() != 1:
                raise RuntimeError("Original first date was not preserved")
            legacy = apps.get_model("assessments", "TopicProgress")
            if legacy.objects.get(user_id=user.pk, topic_id=topic.pk).article_read_at != first:
                raise RuntimeError("Legacy date changed")
            marks.objects.filter(pk=mark.pk).delete()
            legacy.objects.filter(user_id=user.pk, topic_id=topic.pk).delete()
            apps.get_model("accounts", "User").objects.filter(pk=user.pk).delete()
            apps.get_model("learning", "Topic").objects.filter(pk=topic.pk).delete()
            call_command("migrate", check_unapplied=True, verbosity=0)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        connection.close()


if __name__ == "__main__":
    try:
        # Management output remains private; never print connection details or a traceback.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            prepare(sys.argv[1])
    except Exception as error:
        print("VERIFIED_E2E_MIGRATION=FAIL " + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps({"migration": "PASS", "provenance": "PASS", "fixture_cleanup": "PASS"}))
