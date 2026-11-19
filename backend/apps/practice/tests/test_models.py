from copy import deepcopy

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, models, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.accounts.models import User
from apps.learning.changes import EditConflict, IncompleteContent, InvalidRevision
from apps.learning.models import Topic, TopicStatus
from apps.learning.tests.test_content import bilingual_topic
from apps.practice.models import PracticeSubmission, PracticeTask, PracticeTaskTranslation, SubmissionStatus, TopicPractice
from apps.practice.services import build_snapshot

from .factories import create_practice, write


@pytest.fixture
def task(bilingual_topic):
    return create_practice(bilingual_topic)


@pytest.fixture
def row(task, bilingual_topic):
    user = User.objects.create_user("practice-model@example.invalid")
    return PracticeSubmission.objects.create(user=user, task=task, task_snapshot=build_snapshot(task, bilingual_topic))


@pytest.mark.django_db
def test_existing_topics_have_no_implicit_practice_and_draft_can_be_incomplete():
    topic = Topic.objects.create()
    assert not TopicPractice.objects.filter(topic=topic).exists()
    config = write(TopicPractice(topic=topic), topic)
    task = write(PracticeTask(topic_practice=config), topic)
    assert task.status == TopicStatus.DRAFT
    assert not task.translations.exists()


def test_content_admin_registration_and_submission_exclusion():
    for model in (TopicPractice, PracticeTask, PracticeTaskTranslation):
        assert admin.site.is_registered(model)
    assert not admin.site.is_registered(PracticeSubmission)


def test_full_ru_en_can_publish_on_draft_topic_and_every_child_write_bumps_revision(task, bilingual_topic):
    assert task.status == TopicStatus.PUBLISHED
    assert bilingual_topic.status == TopicStatus.DRAFT
    before = bilingual_topic.revision
    write(task.translations.get(language="en"), bilingual_topic, prompt="Revised prompt")
    assert bilingual_topic.revision == before + 1


def test_incomplete_publication_and_published_child_edit_are_atomic(task, bilingual_topic):
    before = bilingual_topic.revision
    translation = task.translations.get(language="en")
    with pytest.raises(IncompleteContent):
        write(translation, bilingual_topic, prompt="")
    assert task.translations.get(language="en").prompt == "en prompt"
    bilingual_topic.refresh_from_db()
    assert bilingual_topic.revision == before
    write(task, bilingual_topic, status=TopicStatus.DRAFT)
    write(translation, bilingual_topic, prompt="")
    before = bilingual_topic.revision
    with pytest.raises(IncompleteContent):
        write(task, bilingual_topic, status=TopicStatus.PUBLISHED)
    task.refresh_from_db()
    bilingual_topic.refresh_from_db()
    assert task.status == TopicStatus.DRAFT and bilingual_topic.revision == before


def test_missing_translation_cannot_publish_and_delete_rolls_back(task, bilingual_topic):
    translation = task.translations.get(language="ru")
    pk = translation.pk
    before = bilingual_topic.revision
    with pytest.raises(IncompleteContent):
        translation.delete(expected_revision=before)
    assert PracticeTaskTranslation.objects.filter(pk=pk).exists()
    bilingual_topic.refresh_from_db()
    assert bilingual_topic.revision == before
    write(task, bilingual_topic, status=TopicStatus.DRAFT)
    translation = task.translations.get(language="ru")
    translation.delete(expected_revision=bilingual_topic.revision)
    with pytest.raises(IncompleteContent):
        write(task, bilingual_topic, status=TopicStatus.PUBLISHED)


def test_canonical_reference_sql_context_and_optimistic_revision(task, bilingual_topic):
    previous = bilingual_topic.revision
    write(task, bilingual_topic, source_text="print('updated')")
    with pytest.raises(EditConflict):
        task.save(expected_revision=previous)
    task.refresh_from_db()
    assert task.source_text == "print('updated')"
    with pytest.raises(IncompleteContent):
        write(task, bilingual_topic, expected_answer=" text ")
    task.refresh_from_db()
    with pytest.raises(IncompleteContent):
        write(task, bilingual_topic, source_type="sql", input_data="")
    task.refresh_from_db()
    write(task, bilingual_topic, source_type="sql", source_text="SELECT COUNT(*) FROM sample;",
          input_data="CREATE TABLE sample(id integer); rows: (1), (2)", environment="PostgreSQL 17.11",
          output_spec="One row/column, integer without header", expected_answer="2")
    assert task.status == TopicStatus.PUBLISHED


def test_parent_links_and_unguarded_writes_are_rejected(task, bilingual_topic):
    with pytest.raises(InvalidRevision):
        task.save()
    with pytest.raises(ValidationError):
        PracticeTask.objects.filter(pk=task.pk).update(status="draft")
    with pytest.raises(ValidationError):
        PracticeTask.objects.bulk_create([PracticeTask(topic_practice=task.topic_practice)])
    another = Topic.objects.create()
    other_config = write(TopicPractice(topic=another), another)
    task.topic_practice = other_config
    with pytest.raises(ValidationError):
        task.save(expected_revision=another.revision)


def raw_insert_rejected(obj):
    with pytest.raises(IntegrityError), transaction.atomic():
        models.Model.save(obj, force_insert=True)
        connection.check_constraints()


def test_postgres_unique_fk_language_and_kind_constraints(task, bilingual_topic):
    raw_insert_rejected(TopicPractice(topic=bilingual_topic))
    raw_insert_rejected(PracticeTask(topic_practice=task.topic_practice))
    raw_insert_rejected(PracticeTask(topic_practice_id=None))
    raw_insert_rejected(PracticeTask(topic_practice_id=2**62))
    raw_insert_rejected(PracticeTaskTranslation(task=task, language="ru"))
    raw_insert_rejected(PracticeTaskTranslation(task=task, language="de"))
    other = Topic.objects.create()
    raw_insert_rejected(TopicPractice(topic=other, practice_kind="unknown"))


@pytest.mark.parametrize("field,value", [
    ("status", "unknown"), ("source_type", "ruby"), ("normalization_mode", "unknown"),
    ("expected_answer", "x" * 5001),
], ids=["status", "source", "mode", "length"])
@pytest.mark.django_db
def test_postgres_task_checks(field, value):
    topic = Topic.objects.create()
    config = write(TopicPractice(topic=topic), topic)
    raw_insert_rejected(PracticeTask(topic_practice=config, **{field: value}))


def test_snapshot_and_parent_identity_are_immutable_at_the_model_boundary(row):
    original = deepcopy(row.task_snapshot)
    row.task_snapshot["normalization_mode"] = "lf_exact_v1"
    with pytest.raises(ValidationError):
        row.save()
    row.refresh_from_db()
    if row.task_snapshot != original:
        pytest.fail("Snapshot changed", pytrace=False)
    with pytest.raises(ValidationError):
        PracticeSubmission.objects.filter(pk=row.pk).update(task_snapshot={})
    row.user = User.objects.create_user("practice-other@example.invalid")
    with pytest.raises(ValidationError):
        row.save()


def test_submitted_fields_cannot_be_rewritten_and_source_is_protected(row, task):
    row.status = SubmissionStatus.SUBMITTED
    row.submitted_answer = "text"
    row.submitted_language = "ru"
    row.verdict = "correct"
    row.submitted_at = timezone.now()
    row.save()
    row.submitted_answer = "changed"
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ProtectedError):
        models.Model.delete(task)
    with pytest.raises(ProtectedError):
        models.Model.delete(task.topic_practice)


def test_constructed_instances_with_existing_ids_cannot_bypass_immutable_identity(row, task, bilingual_topic):
    other_user = User.objects.create_user("practice-replacement@example.invalid")
    with pytest.raises(IntegrityError), transaction.atomic():
        PracticeSubmission(pk=row.pk, user=other_user, task=task, task_snapshot=row.task_snapshot).save()
    assert PracticeSubmission.objects.get(pk=row.pk).user_id == row.user_id
    other_topic = Topic.objects.create()
    other_config = write(TopicPractice(topic=other_topic), other_topic)
    with pytest.raises(IntegrityError), transaction.atomic():
        PracticeTask(pk=task.pk, topic_practice=other_config).save(expected_revision=other_topic.revision)
    assert PracticeTask.objects.get(pk=task.pk).topic_practice_id == task.topic_practice_id


@pytest.mark.parametrize("fields", [
    {"status": "unknown"}, {"submitted_answer": "early"}, {"status": "submitted"},
    {"status": "submitted", "submitted_answer": "x" * 5001, "submitted_language": "ru", "verdict": "correct", "submitted_at": timezone.now()},
    {"status": "submitted", "submitted_answer": "", "submitted_language": "de", "verdict": "correct", "submitted_at": timezone.now()},
    {"status": "submitted", "submitted_answer": "", "submitted_language": "ru", "verdict": "unknown", "submitted_at": timezone.now()},
], ids=["status", "early-answer", "partial-state", "length", "language", "verdict"])
def test_postgres_submission_state_constraints(row, fields):
    raw_insert_rejected(PracticeSubmission(user=row.user, task=row.task, task_snapshot=row.task_snapshot, **fields))


def test_empty_submitted_answer_is_not_null_and_account_cascade_deletes_only_submissions(row):
    pk = row.pk
    row.status = SubmissionStatus.SUBMITTED
    row.submitted_answer = ""
    row.submitted_language = "ru"
    row.verdict = "correct"
    row.submitted_at = timezone.now()
    row.save()
    row.refresh_from_db()
    assert row.submitted_answer == ""
    user = row.user
    user.delete()
    assert not PracticeSubmission.objects.filter(pk=pk).exists()
    assert PracticeTask.objects.filter(pk=row.task_id).exists()
