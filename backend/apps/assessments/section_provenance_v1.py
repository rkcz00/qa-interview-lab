"""Frozen input validation for the section-progress data migration.

A checksum binds a reviewed migration-time export; it does not manufacture proof
from today's positions, timestamps or text. Keep this version for old migrations.
"""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re

from django.db import connections
from django.db.migrations.recorder import MigrationRecorder


SOURCE = "learning.0003_topic_sections"
FILE_ENV = "QIL_SECTION_PROVENANCE_FILE"
DIGEST_ENV = "QIL_SECTION_PROVENANCE_SHA256"


class SectionProvenanceRequired(RuntimeError):
    def __init__(self, reason):
        super().__init__("Section progress migration blocked: " + reason + ". See docs/SECTION_PROGRESS_BACKEND.md.")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SectionProvenanceRequired("duplicate_provenance_key")
        result[key] = value
    return result


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > 2**63 - 1:
        raise SectionProvenanceRequired("invalid_origin_identifier")
    return int(value)


def verified_origins(apps, alias, *, path=None, digest=None):
    """Return explicit origins for every legacy-marked topic, without writing anything."""
    Progress = apps.get_model("assessments", "TopicProgress")
    required = set(Progress.objects.using(alias).values_list("topic_id", flat=True))
    if not required:
        return {}
    path = path if path is not None else os.environ.get(FILE_ENV)
    digest = digest if digest is not None else os.environ.get(DIGEST_ENV)
    if not path or not digest:
        raise SectionProvenanceRequired("verified_provenance_required")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise SectionProvenanceRequired("invalid_provenance_checksum")
    try:
        source = Path(path)
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 1_000_000:
            raise SectionProvenanceRequired("invalid_provenance_file")
        content = source.read_bytes()
        if len(content) > 1_000_000 or hashlib.sha256(content).hexdigest() != digest:
            raise SectionProvenanceRequired("provenance_checksum_mismatch")
        data = json.loads(content, object_pairs_hook=_object)
    except (OSError, UnicodeError, ValueError, TypeError):
        raise SectionProvenanceRequired("unreadable_provenance") from None
    if (not isinstance(data, dict) or set(data) != {"version", "source_migration", "applied_at", "origins"}
            or type(data["version"]) is not int or data["version"] != 1 or data["source_migration"] != SOURCE
            or not isinstance(data["origins"], list)):
        raise SectionProvenanceRequired("invalid_provenance_schema")
    try:
        applied = datetime.fromisoformat(data["applied_at"])
        recorded = MigrationRecorder(connections[alias]).migration_qs.get(app="learning", name="0003_topic_sections").applied
    except (TypeError, ValueError, MigrationRecorder.Migration.DoesNotExist):
        raise SectionProvenanceRequired("migration_binding_missing") from None
    if applied.tzinfo is None or applied.utcoffset() is None or applied != recorded:
        raise SectionProvenanceRequired("migration_binding_mismatch")
    origins = {}
    for row in data["origins"]:
        if not isinstance(row, dict) or set(row) != {"topic_id", "section_id"}:
            raise SectionProvenanceRequired("invalid_origin_entry")
        topic_id = _id(row["topic_id"])
        if topic_id in origins:
            raise SectionProvenanceRequired("duplicate_topic_origin")
        origins[topic_id] = None if row["section_id"] is None else _id(row["section_id"])
    if set(origins) != required:
        raise SectionProvenanceRequired("incomplete_or_unexpected_origin_coverage")
    Section = apps.get_model("learning", "TopicSection")
    existing = {pk: (topic_id, created_at) for pk, topic_id, created_at in Section.objects.using(alias).filter(
        pk__in=[value for value in origins.values() if value is not None],
    ).values_list("pk", "topic_id", "created_at")}
    Topic = apps.get_model("learning", "Topic")
    created = dict(Topic.objects.using(alias).filter(pk__in=required).values_list("pk", "created_at"))
    for topic_id, section_id in origins.items():
        if section_id in existing:
            parent_id, created_at = existing[section_id]
            if parent_id != topic_id:
                raise SectionProvenanceRequired("cross_topic_origin")
            if created_at > recorded:
                raise SectionProvenanceRequired("origin_created_after_source_migration")
        elif section_id is None and created[topic_id] <= recorded:
            raise SectionProvenanceRequired("preexisting_topic_requires_explicit_origin")
    return origins


def backfill_section_progress(apps, schema_editor):
    alias = schema_editor.connection.alias
    origins = verified_origins(apps, alias)
    Section = apps.get_model("learning", "TopicSection")
    existing = set(Section.objects.using(alias).filter(pk__in=[sid for sid in origins.values() if sid is not None]).values_list("pk", flat=True))
    Progress = apps.get_model("assessments", "TopicProgress")
    SectionProgress = apps.get_model("assessments", "TopicSectionProgress")
    pending = []
    for user_id, topic_id, read_at in Progress.objects.using(alias).order_by("pk").values_list("user_id", "topic_id", "article_read_at").iterator():
        section_id = origins[topic_id]
        if section_id in existing:
            pending.append(SectionProgress(user_id=user_id, section_id=section_id, read_at=read_at))
        if len(pending) >= 500:
            SectionProgress.objects.using(alias).bulk_create(pending)
            pending = []
    if pending:
        SectionProgress.objects.using(alias).bulk_create(pending)
