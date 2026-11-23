from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from django.db import transaction

from apps.accounts.models import User
from apps.assessments.models import Attempt, TopicProgress, UserProgressState
from apps.assessments.progress_state import progress_write, reset_progress
from apps.learning.models import Topic, TopicStatus
from apps.learning.tests.test_content import bilingual_topic
from apps.practice.models import PracticeSubmission, PracticeTask

from .pg_locks import wait_for_lock_waiters
from .test_attempts import correct_answers, data
from .test_catalog import sign_in
from .test_content_admin import csrf_header
from .test_practice import practice, started, detail_url, submit_url, delete_url
from .test_registration import assert_error, bootstrap


COMPLETION = "/api/v1/completion-progress/"
RESET = "/api/v1/progress/reset/"


def reset_body():
    return {"confirmation": "reset_all_progress", "request_id": str(uuid4())}


def post_at(client, path, payload, generation="1"):
    return client.post(path, json=payload, headers=csrf_header(client, progress_generation=generation), timeout=15)


def private_keys_absent(value):
    forbidden = {"expected_answer", "content_snapshot", "task_snapshot", "submitted_answer", "submitted_answers",
                 "is_correct", "server_key", "source_revision", "revision", "user_id", "password", "session_id"}
    if isinstance(value, dict):
        assert not set(value).intersection(forbidden)
        for child in value.values():
            private_keys_absent(child)
    elif isinstance(value, list):
        for child in value:
            private_keys_absent(child)


def test_completion_tcp_has_exact_public_shape_states_and_legacy_compatibility(started):
    client, user, topic, task, identifier = started
    old = data(client.get("/api/v1/progress/"))
    response = client.get(COMPLETION)
    result = data(response)
    assert set(result) == {"progress_generation", "overall_completion_progress", "topics"}
    assert result["progress_generation"] == "1" and result["overall_completion_progress"] == 30
    entry = result["topics"][0]
    assert set(entry) == {"topic_id", "article_read_at", "test", "practice", "completion_progress", "mastered"}
    assert entry["test"] == {"status": "failed", "best_result": {"correct_count": 0, "total_count": 2, "percentage": 0}}
    assert entry["practice"] == {"task_id": str(task.pk), "status": "unattempted"}
    assert entry["article_read_at"] == old[0]["article_read_at"] and not entry["mastered"]
    saved = data(post_at(client, submit_url(identifier), {"language": "en", "answer_text": "text"}))
    assert saved["result"] == {"verdict": "correct"}
    entry = data(client.get(COMPLETION))["topics"][0]
    assert entry["completion_progress"] == 65 and entry["practice"]["status"] == "passed" and not entry["mastered"]
    assert "no-store" in response.headers["Cache-Control"] and "Cookie" in response.headers["Vary"]
    private_keys_absent(result)
    assert data(client.get("/api/v1/progress/")) == old
    assert not UserProgressState.objects.filter(user=user).exists()


def test_reset_removes_own_history_including_draft_and_preserves_other_users_content_and_session(started):
    client, user, topic, task, identifier = started
    other = User.objects.create_user("completion-other@example.invalid")
    TopicProgress.objects.create(user=other, topic=topic)
    own_attempt = Attempt.objects.get(user=user)
    foreign_attempt = Attempt.objects.create(user=other, topic=topic, content_snapshot=own_attempt.content_snapshot)
    foreign_work = PracticeSubmission.objects.create(user=other, task=task, task_snapshot=PracticeSubmission.objects.get(pk=identifier).task_snapshot)
    topic.refresh_from_db()
    topic.status = TopicStatus.DRAFT
    topic.save(update_fields=("status",))
    counts = (User.objects.count(), Topic.objects.count(), PracticeTask.objects.count())
    assert data(client.get(COMPLETION))["topics"] == []
    result = data(post_at(client, RESET, reset_body()))
    assert result == {"progress_generation": "2"}
    assert not TopicProgress.objects.filter(user=user).exists()
    assert not Attempt.objects.filter(user=user).exists()
    assert not PracticeSubmission.objects.filter(user=user).exists()
    assert TopicProgress.objects.filter(user=other).count() == 1
    assert Attempt.objects.filter(pk=foreign_attempt.pk).exists() and PracticeSubmission.objects.filter(pk=foreign_work.pk).exists()
    assert counts == (User.objects.count(), Topic.objects.count(), PracticeTask.objects.count())
    assert data(client.get("/api/v1/auth/me/"))["user_id"] == str(user.pk)
    assert data(client.get("/api/v1/progress/")) == []
    assert data(client.get(COMPLETION)) == {"progress_generation": "2", "overall_completion_progress": 0, "topics": []}
    assert_error(client.get(detail_url(identifier)), 404, "not_found")
    assert_error(post_at(client, submit_url(identifier), {}, None), 404, "not_found")
    assert_error(post_at(client, delete_url(identifier), {}, "invalid"), 404, "not_found")
    assert_error(client.get(f"/api/v1/attempts/{own_attempt.pk}/"), 404, "not_found")
    assert_error(post_at(client, f"/api/v1/attempts/{own_attempt.pk}/submit/", {}, None), 404, "not_found")


def test_reset_receipt_repeat_never_deletes_new_work_and_old_receipts_fail_safely(started):
    client, user, topic, _, _ = started
    request = reset_body()
    assert data(post_at(client, RESET, request)) == {"progress_generation": "2"}
    mark = data(post_at(client, f"/api/v1/topics/{topic.pk}/read/", {}, "2"))
    assert data(post_at(client, RESET, request)) == {"progress_generation": "2"}
    assert TopicProgress.objects.get(user=user).article_read_at.isoformat().replace("+00:00", "Z") == mark["article_read_at"]
    assert_error(post_at(client, RESET, request, "2"), 409, "reset_request_conflict")
    assert data(post_at(client, RESET, reset_body(), "2")) == {"progress_generation": "3"}
    post_at(client, f"/api/v1/topics/{topic.pk}/read/", {}, "3")
    assert_error(post_at(client, RESET, request), 409, "progress_reset")
    assert TopicProgress.objects.filter(user=user).count() == 1


@pytest.mark.parametrize("generation", [None, "", "0", "01", "-1", "+1", "1.0", "invalid", "9223372036854775808", "9" * 100])
def test_reset_rejects_invalid_generation_without_writes(started, generation):
    client, user, _, _, _ = started
    counts = (TopicProgress.objects.filter(user=user).count(), Attempt.objects.filter(user=user).count(), PracticeSubmission.objects.filter(user=user).count())
    assert_error(post_at(client, RESET, reset_body(), generation), 400, "validation_error")
    assert counts == (TopicProgress.objects.filter(user=user).count(), Attempt.objects.filter(user=user).count(), PracticeSubmission.objects.filter(user=user).count())
    assert not UserProgressState.objects.exists()


@pytest.mark.parametrize("payload", [{}, {"confirmation": "wrong", "request_id": str(uuid4())},
    {"confirmation": "reset_all_progress", "request_id": "invalid"},
    {"confirmation": "reset_all_progress", "request_id": "00000000-0000-0000-0000-000000000000"},
    {"confirmation": "reset_all_progress", "request_id": str(uuid4()), "user_id": "999"}])
def test_reset_requires_exact_confirmation_and_uuid_without_accepting_an_owner(started, payload):
    client, user, _, _, _ = started
    assert_error(post_at(client, RESET, payload), 400, "validation_error")
    assert TopicProgress.objects.filter(user=user).exists() and not UserProgressState.objects.exists()


def test_reset_csrf_auth_query_method_and_ownership(started):
    client, user, _, _, _ = started
    assert_error(client.post(RESET, json=reset_body(), headers={"X-Progress-Generation": "1"}), 403, "csrf_failed")
    assert_error(client.get(RESET), 405, "method_not_allowed")
    assert_error(post_at(client, RESET + "?extra=1", reset_body()), 400, "validation_error")
    assert_error(client.get(COMPLETION + "?language=ru"), 400, "validation_error")
    with httpx.Client(base_url=client.base_url, trust_env=False) as anonymous:
        assert_error(anonymous.get(COMPLETION), 403, "authentication_required")
        bootstrap(anonymous)
        assert_error(post_at(anonymous, RESET, reset_body()), 403, "authentication_required")
    assert TopicProgress.objects.filter(user=user).exists() and not UserProgressState.objects.exists()


def test_completion_and_reset_are_owner_only_even_for_another_successful_user(started):
    from .test_session import TEST_PASSWORD
    client, _, topic, _, identifier = started
    other = User.objects.create_user("completion-successful-other@example.invalid", TEST_PASSWORD)
    with httpx.Client(base_url=client.base_url, trust_env=False) as sibling:
        sign_in(sibling, other)
        post_at(sibling, f"/api/v1/topics/{topic.pk}/read/", {})
        attempt = data(post_at(sibling, f"/api/v1/topics/{topic.pk}/attempts/", {"language": "ru"}), 201)
        post_at(sibling, f"/api/v1/attempts/{attempt['attempt_id']}/submit/", {"language": "ru", "answers": correct_answers(attempt)})
        own_work = data(post_at(sibling, f"/api/v1/topics/{topic.pk}/practice/submissions/", {"language": "en"}), 201)
        post_at(sibling, submit_url(own_work["submission_id"]), {"language": "en", "answer_text": "text"})
        assert data(sibling.get(COMPLETION))["overall_completion_progress"] == 100
        assert data(client.get(COMPLETION))["overall_completion_progress"] == 30
        assert_error(sibling.get(detail_url(identifier)), 404, "not_found")
        assert_error(post_at(sibling, delete_url(identifier), {}, None), 404, "not_found")
        post_at(client, RESET, reset_body())
        assert data(sibling.get(COMPLETION))["overall_completion_progress"] == 100


def test_reset_generation_overflow_does_not_delete_anything(started):
    client, user, _, _, _ = started
    UserProgressState.objects.create(user=user, generation=2**63 - 1)
    assert_error(post_at(client, RESET, reset_body(), str(2**63 - 1)), 500, "internal_error")
    assert TopicProgress.objects.filter(user=user).exists() and PracticeSubmission.objects.filter(user=user).exists()
    assert UserProgressState.objects.get(user=user).generation == 2**63 - 1


def writes(client, user, topic, identifier):
    attempt = Attempt.objects.get(user=user)
    return {
        "read": (f"/api/v1/topics/{topic.pk}/read/", {}),
        "test_start": (f"/api/v1/topics/{topic.pk}/attempts/", {"language": "ru"}),
        "test_submit": (f"/api/v1/attempts/{attempt.pk}/submit/", {"language": "en", "answers": []}),
        "practice_start": (f"/api/v1/topics/{topic.pk}/practice/submissions/", {"language": "ru"}),
        "practice_submit": (submit_url(identifier), {"language": "ru", "answer_text": "text"}),
        "practice_delete": (delete_url(identifier), {}),
    }


@pytest.mark.parametrize("operation", ["read", "test_start", "test_submit", "practice_start", "practice_submit", "practice_delete"])
def test_every_existing_progress_post_requires_generation(started, operation):
    client, user, topic, _, identifier = started
    path, payload = writes(client, user, topic, identifier)[operation]
    assert_error(post_at(client, path, payload, None), 400, "validation_error")
    assert not UserProgressState.objects.exists()


@pytest.mark.parametrize("operation", ["read", "test_start", "test_submit", "practice_start", "practice_submit", "practice_delete"])
def test_old_generation_cannot_restore_progress_after_reset(started, operation):
    client, user, topic, _, identifier = started
    path, payload = writes(client, user, topic, identifier)[operation]
    post_at(client, RESET, reset_body())
    if operation in ("read", "test_start", "practice_start"):
        assert_error(post_at(client, path, payload), 409, "progress_reset")
    else:
        assert_error(post_at(client, path, payload), 404, "not_found")
    assert not TopicProgress.objects.filter(user=user).exists()
    assert not Attempt.objects.filter(user=user).exists()
    assert not PracticeSubmission.objects.filter(user=user).exists()


def concurrent_post(client, path, payload, headers):
    with httpx.Client(base_url=client.base_url, cookies=client.cookies, trust_env=False, timeout=15) as sibling:
        return sibling.post(path, json=payload, headers=headers)


@pytest.mark.parametrize("operation", ["read", "test_start", "test_submit", "practice_start", "practice_submit", "practice_delete"])
def test_request_already_waiting_on_user_mutex_is_rejected_after_reset(started, operation):
    client, user, topic, _, identifier = started
    path, payload = writes(client, user, topic, identifier)[operation]
    headers = csrf_header(client)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            User.objects.select_for_update().get(pk=user.pk)
            future = pool.submit(concurrent_post, client, path, payload, headers)
            wait_for_lock_waiters(User._meta.db_table, 1)
            with progress_write(user.pk) as state:
                assert reset_progress(state, 1, uuid4()) == "2"
        response = future.result(timeout=15)
    assert_error(response, 409 if operation in ("read", "test_start", "practice_start") else 404,
                 "progress_reset" if operation in ("read", "test_start", "practice_start") else "not_found")
    assert not TopicProgress.objects.filter(user=user).exists()
    assert not Attempt.objects.filter(user=user).exists()
    assert not PracticeSubmission.objects.filter(user=user).exists()


def test_identical_concurrent_resets_have_one_receipt(started):
    client, user, _, _, _ = started
    payload, headers = reset_body(), csrf_header(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(concurrent_post, client, RESET, payload, headers) for _ in range(2)]
        assert [data(f.result(timeout=15)) for f in futures] == [{"progress_generation": "2"}] * 2
    state = UserProgressState.objects.get(user=user)
    assert state.generation == 2 and state.last_reset_from_generation == 1


def test_write_that_wins_the_user_mutex_is_removed_by_the_waiting_reset(started):
    client, user, topic, _, _ = started
    # The first HTTP request owns User and waits for Topic; reset must wait for User.
    headers = csrf_header(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        with transaction.atomic():
            Topic.objects.select_for_update().get(pk=topic.pk)
            writing = pool.submit(concurrent_post, client, f"/api/v1/topics/{topic.pk}/read/", {}, headers)
            wait_for_lock_waiters(Topic._meta.db_table, 1)
            resetting = pool.submit(concurrent_post, client, RESET, reset_body(), headers)
            wait_for_lock_waiters(User._meta.db_table, 1)
        assert writing.result(timeout=15).status_code == 200
        assert data(resetting.result(timeout=15)) == {"progress_generation": "2"}
    assert not TopicProgress.objects.filter(user=user).exists()
    assert not Attempt.objects.filter(user=user).exists()
    assert not PracticeSubmission.objects.filter(user=user).exists()


def test_concurrent_different_reset_requests_cannot_both_advance_generation(started):
    client, user, _, _, _ = started
    headers = csrf_header(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(concurrent_post, client, RESET, reset_body(), headers) for _ in range(2)]
        responses = sorted((future.result(timeout=15) for future in futures), key=lambda response: response.status_code)
    assert data(responses[0]) == {"progress_generation": "2"}
    assert_error(responses[1], 409, "progress_reset")
    assert UserProgressState.objects.get(user=user).generation == 2
