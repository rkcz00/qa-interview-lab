import pytest
from django.db import IntegrityError, transaction
from django.test import Client
from django.utils import timezone

from apps.accounts.models import User
from apps.assessments.attempts import build_snapshot, grade_snapshot
from apps.assessments.models import Attempt, AttemptStatus
from apps.assessments.serializers import PendingAttemptSerializer, SubmittedAttemptSerializer
from apps.learning.models import Topic, TopicStatus
from apps.learning.tests.test_content import bilingual_topic


@pytest.fixture
def stored_attempt(bilingual_topic):
    user = User.objects.create_user("attempt-model@example.invalid")
    return Attempt.objects.create(user=user, topic=bilingual_topic, content_snapshot=build_snapshot(bilingual_topic))


def test_database_protects_snapshot_and_attempt_identity(stored_attempt):
    attempt = stored_attempt
    original = attempt.content_snapshot
    other_user = User.objects.create_user("other-attempt-model@example.invalid")
    other_topic = Topic.objects.create()
    attempts = Attempt.objects.filter(pk=attempt.pk)

    for update in (
        {"id": attempt.pk + 1_000_000},
        {"content_snapshot": {**original, "topic_titles": {"ru": "Changed", "en": "Changed"}}},
        {"user_id": other_user.pk},
        {"topic_id": other_topic.pk},
    ):
        with pytest.raises(IntegrityError) as rejected, transaction.atomic():
            attempts.update(**update)
        assert rejected.value.__cause__.sqlstate == "23514"
    saved = attempts.get()
    assert saved.user_id == attempt.user_id and saved.topic_id == attempt.topic_id
    if saved.content_snapshot != original:
        pytest.fail("The attempt identity protection did not preserve the snapshot", pytrace=False)


def test_database_rejects_incomplete_or_invalid_attempt_state(stored_attempt):
    attempts = Attempt.objects.filter(pk=stored_attempt.pk)
    valid_submission = {
        "status": AttemptStatus.SUBMITTED,
        "submitted_at": timezone.now(),
        "submitted_language": "ru",
        "submitted_answers": grade_snapshot(stored_attempt.content_snapshot, [])[0],
        "correct_count": 0,
        "total_count": 2,
    }
    for update in (
        {"status": AttemptStatus.SUBMITTED},
        {"correct_count": 0},
        {**valid_submission, "total_count": 0},
        {**valid_submission, "correct_count": 3},
        {**valid_submission, "submitted_language": None},
    ):
        with pytest.raises(IntegrityError) as rejected, transaction.atomic():
            attempts.update(**update)
        assert rejected.value.__cause__.diag.constraint_name == "assessments_attempt_valid_state"
    assert attempts.get().status == AttemptStatus.IN_PROGRESS


def test_database_prevents_replacing_a_submitted_result(stored_attempt):
    attempts = Attempt.objects.filter(pk=stored_attempt.pk)
    normalized, result = grade_snapshot(stored_attempt.content_snapshot, [])
    submitted_at = timezone.now()
    attempts.update(
        status=AttemptStatus.SUBMITTED,
        submitted_at=submitted_at,
        submitted_language="ru",
        submitted_answers=normalized,
        correct_count=result["correct_count"],
        total_count=result["total_count"],
    )
    with pytest.raises(IntegrityError) as rejected, transaction.atomic():
        attempts.update(correct_count=1)
    assert rejected.value.__cause__.sqlstate == "23514"
    saved = attempts.get()
    assert saved.correct_count == 0 and saved.submitted_at == submitted_at


@pytest.mark.parametrize("operation", ["start", "submit"])
def test_response_failure_rolls_back_attempt_write(bilingual_topic, monkeypatch, operation):
    topic = bilingual_topic
    topic.status = TopicStatus.PUBLISHED
    topic.save(update_fields=("status",))
    user = User.objects.create_user("attempt-rollback@example.invalid")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    token = client.get("/api/v1/auth/csrf/").json()["data"]["csrf_token"]
    start_url = f"/api/v1/topics/{topic.pk}/attempts/"
    request = {"content_type": "application/json", "HTTP_X_CSRFTOKEN": token}
    if operation == "start":
        url, payload = start_url, {"language": "ru"}
        serializer = PendingAttemptSerializer
    else:
        started = client.post(start_url, {"language": "ru"}, **request)
        assert started.status_code == 201
        attempt_id = started.json()["data"]["attempt_id"]
        url, payload = f"/api/v1/attempts/{attempt_id}/submit/", {"language": "en", "answers": []}
        serializer = SubmittedAttemptSerializer

    status_during_response = []

    def fail_after_write(self, attempt):
        status_during_response.append(Attempt.objects.get(pk=attempt.pk).status)
        raise RuntimeError("Synthetic response failure")

    monkeypatch.setattr(serializer, "to_representation", fail_after_write)
    response = client.post(url, payload, **request)
    assert response.status_code == 500
    assert response.json() == {"error": {
        "code": "internal_error", "message": "Attempt request could not be completed.",
    }}
    if operation == "start":
        assert status_during_response == [AttemptStatus.IN_PROGRESS]
        assert not Attempt.objects.exists()
    else:
        assert status_during_response == [AttemptStatus.SUBMITTED]
        saved = Attempt.objects.get(pk=attempt_id)
        assert saved.status == AttemptStatus.IN_PROGRESS
        assert saved.submitted_at is saved.submitted_answers is saved.correct_count is saved.total_count is None
