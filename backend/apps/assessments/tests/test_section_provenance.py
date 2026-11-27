from datetime import datetime, timezone
import hashlib
import json

import pytest
from django.apps import apps
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from apps.accounts.models import User
from apps.assessments.models import TopicProgress
from apps.assessments.section_provenance_v1 import SectionProvenanceRequired, verified_origins
from apps.learning.models import Topic


def install_manifest(monkeypatch, tmp_path, mapping, *, applied_at=None, mutate=None):
    recorded = MigrationRecorder(connection).migration_qs.get(app="learning", name="0003_topic_sections").applied
    payload = {"version": 1, "source_migration": "learning.0003_topic_sections",
               "applied_at": applied_at or recorded.isoformat(),
               "origins": [{"topic_id": str(topic_id), "section_id": None if section_id is None else str(section_id)}
                           for topic_id, section_id in mapping.items()]}
    if mutate:
        mutate(payload)
    content = json.dumps(payload).encode()
    path = tmp_path / "reviewed-section-provenance.json"
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setenv("QIL_SECTION_PROVENANCE_FILE", str(path))
    monkeypatch.setenv("QIL_SECTION_PROVENANCE_SHA256", digest)
    return path, digest


@pytest.mark.django_db
def test_no_legacy_marks_need_no_manifest_and_preflight_writes_nothing(monkeypatch, capsys):
    monkeypatch.delenv("QIL_SECTION_PROVENANCE_FILE", raising=False)
    monkeypatch.delenv("QIL_SECTION_PROVENANCE_SHA256", raising=False)
    assert verified_origins(apps, "default") == {}
    call_command("check_section_provenance")
    assert "PROVENANCE=PASS legacy_topics=0" in capsys.readouterr().out
    assert not TopicProgress.objects.exists()


@pytest.mark.django_db
def test_ambiguous_legacy_read_requires_explicit_reviewed_provenance(monkeypatch):
    monkeypatch.delenv("QIL_SECTION_PROVENANCE_FILE", raising=False)
    monkeypatch.delenv("QIL_SECTION_PROVENANCE_SHA256", raising=False)
    user = User.objects.create_user("provenance-owner@example.invalid")
    TopicProgress.objects.create(user=user, topic=Topic.objects.create())
    with pytest.raises(SectionProvenanceRequired, match="verified_provenance_required"):
        verified_origins(apps, "default")
    assert TopicProgress.objects.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("fault", ["checksum", "binding", "coverage", "duplicate", "schema", "source"])
def test_provenance_rejects_unverified_binding_coverage_and_schema(monkeypatch, tmp_path, fault):
    user = User.objects.create_user("provenance-invalid@example.invalid")
    topic = Topic.objects.create()
    TopicProgress.objects.create(user=user, topic=topic)
    mutate = None
    if fault == "coverage":
        mutate = lambda body: body.update(origins=[])
    elif fault == "duplicate":
        mutate = lambda body: body["origins"].append(body["origins"][0])
    elif fault == "schema":
        mutate = lambda body: body.update(unexpected="ignored")
    elif fault == "source":
        mutate = lambda body: body.update(source_migration="learning.0002_topic_revision")
    install_manifest(monkeypatch, tmp_path, {topic.pk: None},
                     applied_at="2000-01-01T00:00:00Z" if fault == "binding" else None, mutate=mutate)
    if fault == "checksum":
        monkeypatch.setenv("QIL_SECTION_PROVENANCE_SHA256", "0" * 64)
    with pytest.raises(SectionProvenanceRequired):
        verified_origins(apps, "default")
    assert TopicProgress.objects.count() == 1


@pytest.mark.django_db
def test_explicit_post_migration_topic_without_origin_does_not_invent_section(monkeypatch, tmp_path):
    topic = Topic.objects.create()
    user = User.objects.create_user("post-migration-reader@example.invalid")
    TopicProgress.objects.create(user=user, topic=topic)
    install_manifest(monkeypatch, tmp_path, {topic.pk: None})
    assert verified_origins(apps, "default") == {topic.pk: None}


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("original_exists", [True, False], ids=["existing-origin", "deleted-origin"])
def test_data_migration_requires_provenance_and_copies_only_original_section(monkeypatch, tmp_path, original_exists):
    assert connection.settings_dict["NAME"].startswith("test_qil006_")
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    executor.migrate(latest)
    base = [node for node in latest if node[0] not in {"learning", "assessments"}]
    before = [*base, ("learning", "0002_topic_revision"), ("assessments", "0004_user_progress_state")]
    content_target = [*base, ("learning", "0003_topic_sections"), ("assessments", "0004_user_progress_state")]
    MigrationExecutor(connection).migrate(before)
    old = MigrationExecutor(connection).loader.project_state(before).apps
    try:
        topic = old.get_model("learning", "Topic").objects.create(status="published", revision=8)
        for language in ("ru", "en"):
            old.get_model("learning", "TopicTranslation").objects.create(
                topic_id=topic.pk, language=language, title=language+" legacy", article_body=language+" original",
            )
        user = old.get_model("accounts", "User").objects.create(email="original-reader@example.invalid", password="!")
        first = datetime(2025, 2, 3, 4, 5, 6, tzinfo=timezone.utc)
        old.get_model("assessments", "TopicProgress").objects.create(user_id=user.pk, topic_id=topic.pk, article_read_at=first)
        old.get_model("assessments", "UserProgressState").objects.create(user_id=user.pk, generation=7)
        old.get_model("assessments", "Attempt").objects.create(user_id=user.pk, topic_id=topic.pk, content_snapshot={"historical": ["keep"]})
        tracked = [("learning", "Topic"), ("learning", "TopicTranslation"), ("accounts", "User"),
                   ("assessments", "Attempt"), ("assessments", "TopicProgress"), ("assessments", "UserProgressState")]
        unchanged = {key: list(old.get_model(*key).objects.order_by("pk").values()) for key in tracked}
        MigrationExecutor(connection).migrate(content_target)
        state = MigrationExecutor(connection).loader.project_state(content_target).apps
        Section = state.get_model("learning", "TopicSection")
        # The controlled test records the output immediately after learning 0003.
        original = Section.objects.get(topic_id=topic.pk)
        later = Section.objects.create(topic_id=topic.pk, status="published", position=20)
        for language in ("ru", "en"):
            state.get_model("learning", "TopicSectionTranslation").objects.create(
                section_id=later.pk, language=language, title=language+" later", article_body=language+" later body",
            )
        monkeypatch.delenv("QIL_SECTION_PROVENANCE_FILE", raising=False)
        monkeypatch.delenv("QIL_SECTION_PROVENANCE_SHA256", raising=False)
        with pytest.raises(SectionProvenanceRequired, match="verified_provenance_required"):
            MigrationExecutor(connection).migrate(latest)
        assert "assessments_topicsectionprogress" not in connection.introspection.table_names()
        assert state.get_model("assessments", "TopicProgress").objects.get().article_read_at == first
        install_manifest(monkeypatch, tmp_path, {topic.pk: later.pk})
        with pytest.raises(SectionProvenanceRequired, match="origin_created_after_source_migration"):
            MigrationExecutor(connection).migrate(latest)
        assert "assessments_topicsectionprogress" not in connection.introspection.table_names()
        install_manifest(monkeypatch, tmp_path, {topic.pk: original.pk})
        original_id = original.pk
        if not original_exists:
            original.delete()
        MigrationExecutor(connection).migrate(latest)
        new = MigrationExecutor(connection).loader.project_state(latest).apps
        assert unchanged == {key: list(new.get_model(*key).objects.order_by("pk").values()) for key in tracked}
        marks = list(new.get_model("assessments", "TopicSectionProgress").objects.values_list("user_id", "section_id", "read_at"))
        assert marks == ([(user.pk, original_id, first)] if original_exists else [])
        assert not new.get_model("assessments", "TopicSectionProgress").objects.filter(section_id=later.pk).exists()
    finally:
        # Only this test's disposable database is touched; always restore the full graph.
        state = MigrationExecutor(connection).loader.project_state(content_target).apps
        state.get_model("assessments", "TopicProgress").objects.all().delete()
        MigrationExecutor(connection).migrate(latest)
