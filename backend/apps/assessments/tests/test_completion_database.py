from uuid import uuid4

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from django.utils import timezone
import pytest

from apps.accounts.models import User
from apps.assessments.completion import completion_progress
from apps.assessments.models import Attempt, TopicProgress, UserProgressState
from apps.assessments.serializers import CompletionProgressSerializer
from apps.learning.models import Topic
from apps.learning.tests.test_content import bilingual_topic
from apps.practice.models import PracticeSubmission, SubmissionStatus
from apps.practice.services import build_snapshot
from apps.practice.tests.factories import create_practice, write
from tests.api.test_catalog import publish
from tests.api.test_progress import store_historical_result


pytestmark = pytest.mark.django_db


def finished_practice(user, task, verdict):
    row = PracticeSubmission.objects.create(
        user=user, task=task, task_snapshot=build_snapshot(task, task.topic_practice.topic),
    )
    row.status = SubmissionStatus.SUBMITTED
    row.submitted_answer = "text" if verdict == "correct" else "synthetic mismatch"
    row.submitted_language = "ru"
    row.submitted_at = timezone.now()
    row.verdict = verdict
    row.save()
    return row


def projected(user):
    return CompletionProgressSerializer(completion_progress(user.pk)).data


def test_completion_gets_a_single_statement_snapshot_and_never_creates_state(bilingual_topic, django_assert_num_queries):
    user = User.objects.create_user("completion-reader@example.invalid")
    publish(bilingual_topic)
    with django_assert_num_queries(1):
        result = projected(user)
    assert result == {
        "progress_generation": "1", "overall_completion_progress": 0,
        "topics": [{"topic_id": str(bilingual_topic.pk), "article_read_at": None,
                    "test": {"status": "unattempted", "best_result": None}, "practice": None,
                    "completion_progress": 0, "mastered": False}],
    }
    assert not UserProgressState.objects.exists()


def test_completion_empty_catalog_has_generation_and_zero_without_writes(django_assert_num_queries):
    user = User.objects.create_user("completion-empty@example.invalid")
    with django_assert_num_queries(1):
        assert projected(user) == {"progress_generation": "1", "overall_completion_progress": 0, "topics": []}
    assert not UserProgressState.objects.exists()


def test_completion_uses_best_snapshot_and_retained_correct_without_changing_mastery(bilingual_topic):
    user = User.objects.create_user("completion-best@example.invalid")
    task = create_practice(bilingual_topic)
    publish(bilingual_topic)
    mark = TopicProgress.objects.create(user=user, topic=bilingual_topic)
    first = store_historical_result(user, bilingual_topic, 4, 5)
    store_historical_result(user, bilingual_topic, 1, 5, language="en")
    value = projected(user)["topics"][0]
    assert value["test"]["status"] == "passed" and value["test"]["best_result"]["correct_count"] == first.correct_count
    assert value["completion_progress"] == 65 and value["mastered"] is True
    successful = finished_practice(user, task, "correct")
    finished_practice(user, task, "incorrect")
    assert projected(user)["topics"][0]["completion_progress"] == 100
    successful.delete()
    value = projected(user)["topics"][0]
    assert value["practice"]["status"] == "failed" and value["completion_progress"] == 65
    assert value["mastered"] is True
    mark.refresh_from_db()
    assert value["article_read_at"] == mark.article_read_at.isoformat().replace("+00:00", "Z")
    write(task, bilingual_topic, status="draft")
    value = projected(user)["topics"][0]
    assert value["practice"] is None and value["completion_progress"] == 100 and value["mastered"]


def test_failed_completed_test_can_coexist_with_correct_practice_and_no_mastery(bilingual_topic):
    user = User.objects.create_user("completion-failed@example.invalid")
    task = create_practice(bilingual_topic)
    publish(bilingual_topic)
    TopicProgress.objects.create(user=user, topic=bilingual_topic)
    store_historical_result(user, bilingual_topic, 1, 2)
    finished_practice(user, task, "correct")
    value = projected(user)["topics"][0]
    assert value["test"]["status"] == "failed" and value["practice"]["status"] == "passed"
    assert value["completion_progress"] == 65 and value["mastered"] is False


@pytest.mark.parametrize("fields", [
    {"generation": 0},
    {"last_reset_request_id": uuid4()},
    {"last_reset_from_generation": 1},
    {"generation": 3, "last_reset_from_generation": 1, "last_reset_request_id": uuid4()},
])
def test_state_constraints_reject_invalid_receipts(fields):
    user = User.objects.create_user("completion-constraint@example.invalid")
    with pytest.raises(IntegrityError), transaction.atomic():
        UserProgressState.objects.create(user=user, **fields)


def test_state_is_one_to_one_and_private():
    from django.contrib import admin
    from django.contrib.auth.models import Group
    user = User.objects.create_user("completion-state@example.invalid")
    UserProgressState.objects.create(user=user)
    with pytest.raises(IntegrityError), transaction.atomic():
        UserProgressState.objects.create(user=user)
    assert not admin.site.is_registered(UserProgressState)
    assert not Group.objects.get(name="Content Admin").permissions.filter(content_type__model="userprogressstate").exists()


@pytest.mark.parametrize("failure", ["state_save", "response"])
def test_reset_rolls_back_deleted_rows_and_receipt_on_failure(bilingual_topic, monkeypatch, failure):
    from apps.assessments import views
    user = User.objects.create_user("completion-rollback@example.invalid")
    task = create_practice(bilingual_topic)
    publish(bilingual_topic)
    TopicProgress.objects.create(user=user, topic=bilingual_topic)
    store_historical_result(user, bilingual_topic, 1, 2)
    finished_practice(user, task, "correct")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    token = client.get("/api/v1/auth/csrf/").json()["data"]["csrf_token"]
    def broken(*args, **kwargs):
        raise RuntimeError("Synthetic reset failure")
    if failure == "state_save":
        monkeypatch.setattr(UserProgressState, "save", broken)
    else:
        monkeypatch.setattr(views, "JsonResponse", broken)
    response = client.post("/api/v1/progress/reset/", {
        "confirmation": "reset_all_progress", "request_id": str(uuid4()),
    }, content_type="application/json", HTTP_X_CSRFTOKEN=token, HTTP_X_PROGRESS_GENERATION="1")
    assert response.status_code == 500 and response.json()["error"]["code"] == "internal_error"
    assert TopicProgress.objects.filter(user=user).count() == 1
    assert Attempt.objects.filter(user=user).count() == 1
    assert PracticeSubmission.objects.filter(user=user).count() == 1
    assert not UserProgressState.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_state_migration_preserves_existing_user_content_read_and_snapshots(bilingual_topic):
    user = User.objects.create_user("completion-migration@example.invalid")
    task = create_practice(bilingual_topic)
    publish(bilingual_topic)
    mark = TopicProgress.objects.create(user=user, topic=bilingual_topic)
    attempt = store_historical_result(user, bilingual_topic, 1, 2)
    work = finished_practice(user, task, "correct")
    try:
        MigrationExecutor(connection).migrate([("assessments", "0003_topic_progress")])
        MigrationExecutor(connection).migrate([("assessments", "0004_user_progress_state")])
        assert User.objects.filter(pk=user.pk).exists() and Topic.objects.filter(pk=bilingual_topic.pk).exists()
        assert TopicProgress.objects.get(pk=mark.pk).article_read_at == mark.article_read_at
        assert Attempt.objects.get(pk=attempt.pk).content_snapshot == attempt.content_snapshot
        assert PracticeSubmission.objects.get(pk=work.pk).task_snapshot == work.task_snapshot
        assert not UserProgressState.objects.exists()
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
