from datetime import datetime, timezone as dt_timezone

import pytest
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client

from apps.accounts.models import User
from apps.assessments.models import TopicProgress
from apps.assessments.progress import summarize_progress, user_progress
from apps.assessments.serializers import ProgressSerializer, ReadTopicSerializer
from apps.learning.models import Topic, TopicStatus
from apps.learning.tests.test_content import bilingual_topic


READ_AT = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)


@pytest.mark.parametrize(
    "counts,percentage,qualifies",
    [((7999, 10000), 79.99, False), ((8000, 10000), 80.0, True), ((8001, 10000), 80.01, True),
     ((39999, 50000), 80.0, False), ((1, 32), 3.13, False)],
)
@pytest.mark.parametrize("read_at", [None, READ_AT], ids=["unread", "read"])
def test_progress_uses_exact_mastery_and_half_up_display(counts, percentage, qualifies, read_at):
    assert summarize_progress(7, read_at, [counts]) == {
        "topic_id": "7", "article_read_at": read_at,
        "best_result": {"correct_count": counts[0], "total_count": counts[1], "percentage": percentage},
        "mastered": qualifies and read_at is not None,
    }


@pytest.mark.parametrize(
    "counts,expected,mastered",
    [([], None, False),
     ([(3, 5), (1, 2)], {"correct_count": 3, "total_count": 5, "percentage": 60.0}, False),
     ([(39999, 50000), (4, 5), (1, 5)], {"correct_count": 4, "total_count": 5, "percentage": 80.0}, True),
     ([(4, 5), (8, 10)], {"correct_count": 4, "total_count": 5, "percentage": 80.0}, True)],
)
def test_best_result_is_one_attempt_compared_before_rounding(counts, expected, mastered):
    progress = summarize_progress(7, READ_AT, counts)
    assert progress["best_result"] == expected
    assert progress["mastered"] is mastered


def test_progress_serializer_never_exposes_internal_fields():
    progress = {
        **summarize_progress(7, None, []), "user_id": "private", "revision": 9,
        "content_snapshot": {}, "submitted_answers": [],
    }
    assert ProgressSerializer(progress).data == {
        "topic_id": "7", "article_read_at": None, "best_result": None, "mastered": False,
    }
    progress["best_result"] = {"correct_count": 4, "total_count": 5, "percentage": 80.0, "server_key": "private"}
    assert set(ProgressSerializer(progress).data["best_result"]) == {"correct_count", "total_count", "percentage"}


@pytest.mark.parametrize("payload", [{}, None, [], "read", 1, False, {"language": "en"}, {"user_id": "1"}])
def test_read_request_accepts_only_an_empty_json_object(payload):
    serializer = ReadTopicSerializer(data=payload)
    assert serializer.is_valid() is (payload == {} and isinstance(payload, dict))


@pytest.mark.parametrize("counts", [(0, 0), (-1, 5), (6, 5), (True, 1)])
def test_progress_rejects_invalid_stored_counts(counts):
    with pytest.raises(ValueError):
        summarize_progress(7, READ_AT, [counts])


@pytest.mark.django_db
def test_database_enforces_one_mark_per_owner_and_protects_topic():
    user = User.objects.create_user("progress-model@example.invalid")
    topic = Topic.objects.create()
    mark = TopicProgress.objects.create(user=user, topic=topic, article_read_at=READ_AT)
    with pytest.raises(IntegrityError) as duplicate, transaction.atomic():
        TopicProgress.objects.create(user=user, topic=topic)
    assert duplicate.value.__cause__.diag.constraint_name == "assessments_topic_progress_owner_unique"
    with pytest.raises(IntegrityError) as null_mark, transaction.atomic():
        TopicProgress.objects.filter(pk=mark.pk).update(article_read_at=None)
    assert null_mark.value.__cause__.sqlstate == "23502"
    other = User.objects.create_user("other-progress-model@example.invalid")
    TopicProgress.objects.create(user=other, topic=topic)
    TopicProgress.objects.create(user=user, topic=Topic.objects.create())
    with pytest.raises(ProtectedError):
        topic.delete()
    assert TopicProgress.objects.get(pk=mark.pk).article_read_at == READ_AT
    assert TopicProgress.objects.count() == 3


@pytest.mark.django_db
def test_progress_read_does_not_create_marks_and_uses_bounded_queries(django_assert_num_queries):
    user = User.objects.create_user("progress-query@example.invalid")
    other = User.objects.create_user("other-progress-query@example.invalid")
    topics = [Topic.objects.create() for _ in range(3)]
    for topic in topics:
        TopicProgress.objects.create(user=user, topic=topic, article_read_at=READ_AT)
    TopicProgress.objects.create(user=other, topic=topics[0])
    with django_assert_num_queries(2):
        progress = user_progress(user.pk)
    assert progress == [summarize_progress(topic.pk, READ_AT, []) for topic in topics]
    assert TopicProgress.objects.count() == 4


def test_read_response_failure_rolls_back_mark(bilingual_topic, monkeypatch):
    topic = bilingual_topic
    topic.status = TopicStatus.PUBLISHED
    topic.save(update_fields=("status",))
    user = User.objects.create_user("progress-rollback@example.invalid")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    token = client.get("/api/v1/auth/csrf/").json()["data"]["csrf_token"]
    writes_during_response = []

    def fail_after_write(self, progress):
        writes_during_response.append(TopicProgress.objects.filter(user=user, topic=topic).count())
        raise RuntimeError("Synthetic progress response failure")

    monkeypatch.setattr(ProgressSerializer, "to_representation", fail_after_write)
    response = client.post(
        f"/api/v1/topics/{topic.pk}/read/", {}, content_type="application/json", HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 500
    assert response.json() == {"error": {
        "code": "internal_error", "message": "Progress request could not be completed.",
    }}
    assert writes_during_response == [1]
    assert not TopicProgress.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_migration_preserves_existing_users_topics_and_attempts(bilingual_topic):
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from apps.assessments.attempts import build_snapshot

    before = ("assessments", "0002_attempt")
    after = ("assessments", "0003_topic_progress")
    topic = bilingual_topic
    topic.status = TopicStatus.PUBLISHED
    topic.save(update_fields=("status",))
    snapshot = build_snapshot(topic)
    executor = MigrationExecutor(connection)
    try:
        executor.migrate([before])
        historical = executor.loader.project_state([before]).apps
        user = historical.get_model("accounts", "User").objects.create(email="progress-upgrade@example.invalid")
        attempt = historical.get_model("assessments", "Attempt").objects.create(
            user_id=user.pk, topic_id=topic.pk, content_snapshot=snapshot,
        )
        executor = MigrationExecutor(connection)
        executor.migrate([after])
        current = executor.loader.project_state([after]).apps
        assert current.get_model("accounts", "User").objects.get(pk=user.pk).email == user.email
        assert current.get_model("learning", "Topic").objects.filter(pk=topic.pk).exists()
        saved = current.get_model("assessments", "Attempt").objects.get(pk=attempt.pk)
        assert saved.user_id == user.pk and saved.topic_id == topic.pk
        if saved.content_snapshot != snapshot:
            pytest.fail("Progress migration changed an existing snapshot", pytrace=False)
        assert saved.status == "in_progress"
        assert not current.get_model("assessments", "TopicProgress").objects.exists()
    finally:
        MigrationExecutor(connection).migrate([after])
