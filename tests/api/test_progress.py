from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
import json

import httpx
import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.assessments.attempts import build_snapshot, grade_snapshot
from apps.assessments.models import Attempt, AttemptStatus, QuestionType, TopicProgress
from apps.learning.changes import edit_topics
from apps.learning.models import Topic, TopicStatus
from apps.learning.tests.test_content import bilingual_topic

from .pg_locks import wait_for_lock_waiters
from .test_attempts import correct_answers, data, learner, post, start, start_url, submit_url
from .test_catalog import article_url, publish, sign_in, terms_url
from .test_content_admin import admin_url, content_editor, csrf_header
from .test_content_admin import sign_in as sign_in_admin
from .test_registration import assert_error, bootstrap
from .test_session import TEST_PASSWORD


PROGRESS_URL = "/api/v1/progress/"


def read_url(topic_id):
    return f"/api/v1/topics/{topic_id}/read/"


def assert_progress(payload, topic_id, read_at=None, result=None, mastered=False):
    assert payload == {
        "topic_id": str(topic_id), "article_read_at": read_at, "best_result": result, "mastered": mastered,
    }


def store_historical_result(user, topic, correct_count, total_count, language="ru"):
    """Seed a consistent, server-only historical snapshot and score, with no current-content dependency."""
    snapshot = build_snapshot(topic)
    template = next(q for q in snapshot["questions"] if q["question_type"] == QuestionType.SINGLE_CHOICE)
    snapshot["questions"] = []
    answers = []
    for index in range(total_count):
        question = deepcopy(template)
        question["question_id"] = str(1_000_000 + index)
        question["position"] = index
        for choice_index, choice in enumerate(question["choices"]):
            choice["choice_id"] = str(10_000_000 + index * len(question["choices"]) + choice_index)
        if index < correct_count:
            answers.append({
                "question_id": question["question_id"],
                "choice_ids": [choice["choice_id"] for choice in question["choices"] if choice["is_correct"]],
            })
        snapshot["questions"].append(question)
    normalized, result = grade_snapshot(snapshot, answers)
    assert result["correct_count"] == correct_count and result["total_count"] == total_count
    return Attempt.objects.create(
        user=user, topic=topic, status=AttemptStatus.SUBMITTED, content_snapshot=snapshot,
        submitted_at=timezone.now(), submitted_language=language, submitted_answers=normalized,
        correct_count=correct_count, total_count=total_count,
    )


def test_read_is_explicit_idempotent_and_persists_after_login(learner, bilingual_topic):
    client, user = learner
    topic = bilingual_topic
    publish(topic)
    for language in ("ru", "en"):
        assert client.get(article_url(topic.pk), params={"language": language}).status_code == 200
        assert client.get(terms_url(topic.pk), params={"language": language}).status_code == 200
    assert data(client.get(PROGRESS_URL)) == []
    assert not TopicProgress.objects.exists()
    marked_response = post(client, read_url(topic.pk), {})
    marked = data(marked_response)
    read_at = marked["article_read_at"]
    assert datetime.fromisoformat(read_at).utcoffset() == timedelta(0)
    assert_progress(marked, topic.pk, read_at=read_at)
    stored = TopicProgress.objects.get(user=user, topic=topic)
    assert stored.article_read_at == datetime.fromisoformat(read_at)
    assert data(post(client, read_url(topic.pk), {})) == marked
    assert data(client.get(PROGRESS_URL)) == [marked]
    assert TopicProgress.objects.filter(user=user, topic=topic).count() == 1
    for response in (marked_response, client.get(PROGRESS_URL)):
        assert "no-store" in response.headers["Cache-Control"]
        assert "Cookie" in response.headers["Vary"]
    assert post(client, "/api/v1/auth/logout/", {}).status_code == 204
    assert_error(client.get(PROGRESS_URL), 403, "authentication_required")
    sign_in(client, user)
    assert data(client.get(PROGRESS_URL)) == [marked]


@pytest.mark.parametrize("article_language,test_language,read_first", [("ru", "en", True), ("en", "ru", False)])
def test_read_and_test_languages_share_one_progress_in_both_orders(
    learner, bilingual_topic, article_language, test_language, read_first,
):
    client, user = learner
    topic = bilingual_topic
    publish(topic)
    assert client.get(article_url(topic.pk), params={"language": article_language}).status_code == 200
    pending = start(client, topic, test_language)
    assert data(client.get(PROGRESS_URL)) == []
    if read_first:
        marked = data(post(client, read_url(topic.pk), {}))
        assert_progress(marked, topic.pk, read_at=marked["article_read_at"])
    result = data(post(client, submit_url(pending["attempt_id"]), {
        "language": test_language, "answers": correct_answers(pending),
    }))["result"]
    assert result == {"correct_count": 2, "total_count": 2, "percentage": 100.0}
    if not read_first:
        assert_progress(data(client.get(PROGRESS_URL))[0], topic.pk, result=result)
        assert not TopicProgress.objects.exists()
        post(client, read_url(topic.pk), {}).raise_for_status()
    marked = data(client.get(PROGRESS_URL))[0]
    assert_progress(marked, topic.pk, read_at=marked["article_read_at"], result=result, mastered=True)
    assert TopicProgress.objects.filter(user=user, topic=topic).count() == 1
    later = start(client, topic, article_language)
    post(client, submit_url(later["attempt_id"]), {"language": article_language, "answers": []}).raise_for_status()
    start(client, topic, test_language)  # An unfinished attempt cannot replace the result.
    assert data(client.get(PROGRESS_URL)) == [marked]
    assert data(post(client, read_url(topic.pk), {})) == marked


@pytest.mark.parametrize("correct_count,percentage,mastered", [(7999, 79.99, False), (8000, 80.0, True), (8001, 80.01, True)])
def test_http_progress_uses_saved_exact_threshold_counts(learner, bilingual_topic, correct_count, percentage, mastered):
    client, user = learner
    topic = bilingual_topic
    publish(topic)
    marked = data(post(client, read_url(topic.pk), {}))
    store_historical_result(user, topic, correct_count, 10000)
    assert_progress(data(client.get(PROGRESS_URL))[0], topic.pk, read_at=marked["article_read_at"], result={
        "correct_count": correct_count, "total_count": 10000, "percentage": percentage,
    }, mastered=mastered)


def test_best_result_does_not_sum_failures_and_keeps_an_earlier_success(learner, bilingual_topic):
    client, user = learner
    topic = bilingual_topic
    publish(topic)
    marked = data(post(client, read_url(topic.pk), {}))
    store_historical_result(user, topic, 3, 5)
    store_historical_result(user, topic, 1, 2, "en")
    assert_progress(data(client.get(PROGRESS_URL))[0], topic.pk, read_at=marked["article_read_at"], result={
        "correct_count": 3, "total_count": 5, "percentage": 60.0,
    })
    store_historical_result(user, topic, 4, 5, "en")
    store_historical_result(user, topic, 8, 10)
    store_historical_result(user, topic, 0, 2)
    assert_progress(data(client.get(PROGRESS_URL))[0], topic.pk, read_at=marked["article_read_at"], result={
        "correct_count": 4, "total_count": 5, "percentage": 80.0,
    }, mastered=True)


def test_saved_progress_survives_edits_draft_and_old_snapshot_submission(learner, bilingual_topic):
    client, user = learner
    topic = bilingual_topic
    publish(topic)
    marked = data(post(client, read_url(topic.pk), {}))
    failed = start(client, topic)
    post(client, submit_url(failed["attempt_id"]), {"language": "ru", "answers": []}).raise_for_status()
    pending = start(client, topic, "en")
    before = data(client.get(PROGRESS_URL))
    assert before[0]["mastered"] is False
    with edit_topics({topic.pk: topic.revision}, using="default"):
        topic.translations.update(article_body="Edited published article")
    assert data(client.get(PROGRESS_URL)) == before
    topic.refresh_from_db()
    with edit_topics({topic.pk: topic.revision}, using="default") as topics:
        topics[topic.pk].status = TopicStatus.DRAFT
        topic.translations.update(article_body="Private Draft article")
        topic.questions.all().delete()
    assert data(client.get(PROGRESS_URL)) == before
    for url in (article_url(topic.pk), terms_url(topic.pk)):
        assert_error(client.get(url), 404, "not_found")
    assert_error(post(client, read_url(topic.pk), {}), 404, "not_found")
    assert_error(post(client, start_url(topic.pk), {"language": "ru"}), 404, "not_found")
    submitted = data(post(client, submit_url(pending["attempt_id"]), {
        "language": "en", "answers": correct_answers(pending),
    }))
    after = data(client.get(PROGRESS_URL))[0]
    assert_progress(after, topic.pk, read_at=marked["article_read_at"], result=submitted["result"], mastered=True)
    assert TopicProgress.objects.filter(user=user, topic=topic).count() == 1
    assert Attempt.objects.filter(user=user, topic=topic).count() == 2


@pytest.mark.parametrize("role", ["learner", "staff", "content_admin", "superuser"])
def test_progress_is_scoped_to_owner_for_every_role(learner, bilingual_topic, role):
    client, owner = learner
    topic = bilingual_topic
    publish(topic)
    data(post(client, read_url(topic.pk), {}))
    pending = start(client, topic)
    post(client, submit_url(pending["attempt_id"]), {"language": "ru", "answers": correct_answers(pending)}).raise_for_status()
    own = data(client.get(PROGRESS_URL))
    if role == "superuser":
        other = User.objects.create_superuser("other-progress@example.invalid", TEST_PASSWORD)
    else:
        other = User.objects.create_user("other-progress@example.invalid", TEST_PASSWORD, is_staff=role != "learner")
        if role == "content_admin":
            other.groups.add(Group.objects.get(name="Content Admin"))
    with httpx.Client(base_url=client.base_url, trust_env=False) as outsider:
        sign_in(outsider, other)
        assert data(outsider.get(PROGRESS_URL)) == []
        assert_error(outsider.get(PROGRESS_URL, params={"user_id": str(owner.pk)}), 400, "validation_error")
        assert_error(post(outsider, read_url(topic.pk), {"user_id": str(owner.pk)}), 400, "validation_error")
        marked = data(post(outsider, read_url(topic.pk), {}))
        assert_progress(marked, topic.pk, read_at=marked["article_read_at"])
        assert data(outsider.get(PROGRESS_URL)) == [marked]
    assert data(client.get(PROGRESS_URL)) == own
    assert TopicProgress.objects.filter(topic=topic).count() == 2


def test_progress_requires_session_csrf_and_strict_requests(learner, bilingual_topic):
    client, user = learner
    topic = bilingual_topic
    publish(topic)
    url = read_url(topic.pk)
    with httpx.Client(base_url=client.base_url, trust_env=False) as anonymous:
        assert_error(anonymous.get(PROGRESS_URL), 403, "authentication_required")
        bootstrap(anonymous)
        assert_error(post(anonymous, url, {}), 403, "authentication_required")
    for case in ("missing-cookie", "missing-header", "mismatch"):
        token = bootstrap(client)
        headers = {"X-CSRFToken": token}
        if case == "missing-cookie":
            client.cookies.delete(settings.CSRF_COOKIE_NAME)
        elif case == "missing-header":
            headers = {}
        else:
            headers["X-CSRFToken"] = ("A" if token[0] != "A" else "B") + token[1:]
        assert_error(client.post(url, json={}, headers=headers), 403, "csrf_failed")
        assert not TopicProgress.objects.exists()
    bootstrap(client)
    for payload in (None, [], "read", {"language": "en"}, {"article_read_at": "2026-01-01"}, {"mastered": True}):
        response = client.post(url, content=json.dumps(payload), headers={**csrf_header(client), "Content-Type": "application/json"})
        assert_error(response, 400, "validation_error")
    assert_error(client.post(url, content="{", headers={**csrf_header(client), "Content-Type": "application/json"}), 400, "validation_error")
    assert_error(client.post(url, content="read", headers={**csrf_header(client), "Content-Type": "text/plain"}), 415, "unsupported_media_type")
    assert_error(client.get(url), 405, "method_not_allowed")
    assert_error(post(client, PROGRESS_URL, {}), 405, "method_not_allowed")
    assert_error(client.get(PROGRESS_URL, params={"language": "en"}), 400, "validation_error")
    assert_error(post(client, url + "?language=ru", {}), 400, "validation_error")
    draft = Topic.objects.create()
    missing = post(client, read_url("9223372036854775807"), {})
    assert_error(missing, 404, "not_found")
    for topic_id in (str(draft.pk), "unknown", "0", "01"):
        response = post(client, read_url(topic_id), {})
        assert_error(response, 404, "not_found")
        assert response.json() == missing.json()
    assert not TopicProgress.objects.filter(user=user).exists()


def test_concurrent_read_marks_keep_one_row_and_the_first_timestamp(learner, bilingual_topic):
    client, user = learner
    topic = bilingual_topic
    publish(topic)
    with httpx.Client(base_url=client.base_url, trust_env=False) as second_client:
        sign_in(second_client, user)
        with ThreadPoolExecutor(max_workers=2) as pool:
            with transaction.atomic():
                Topic.objects.select_for_update().get(pk=topic.pk)
                first = pool.submit(post, client, read_url(topic.pk), {})
                wait_for_lock_waiters("learning_topic", 1)
                second = pool.submit(post, second_client, read_url(topic.pk), {})
                wait_for_lock_waiters("learning_topic", 2)
            marked = data(first.result(timeout=15))
            assert data(second.result(timeout=15)) == marked
    assert TopicProgress.objects.filter(user=user, topic=topic).count() == 1
    assert data(client.get(PROGRESS_URL)) == [marked]


def test_read_waits_for_unpublication_and_creates_no_mark(learner, bilingual_topic):
    client, _ = learner
    publish(bilingual_topic)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            topic = Topic.objects.select_for_update().get(pk=bilingual_topic.pk)
            marking = pool.submit(post, client, read_url(topic.pk), {})
            wait_for_lock_waiters("learning_topic", 1)
            topic.status = TopicStatus.DRAFT
            topic.save(update_fields=("status",))
        assert_error(marking.result(timeout=15), 404, "not_found")
    assert not TopicProgress.objects.exists()


def test_content_admin_cannot_open_progress_or_delete_topic_with_read_mark(learner, bilingual_topic):
    client, _ = learner
    topic = bilingual_topic
    publish(topic)
    data(post(client, read_url(topic.pk), {}))
    mark = TopicProgress.objects.get(topic=topic)
    assert not Attempt.objects.exists()
    editor = content_editor("progress-content-editor")
    for action in ("view", "add", "change", "delete"):
        assert not editor.has_perm(f"assessments.{action}_topicprogress")
    with httpx.Client(base_url=client.base_url, trust_env=False) as admin_client:
        sign_in_admin(admin_client, editor)
        for url in ("/admin/assessments/topicprogress/", f"/admin/assessments/topicprogress/{mark.pk}/change/"):
            assert admin_client.get(url).status_code == 404
        deletion = admin_url(Topic, "delete", topic)
        response = admin_client.get(deletion)
        assert response.status_code == 200
        response = admin_client.post(deletion, data={"post": "yes", "expected_revision": topic.revision}, headers=csrf_header(admin_client))
        assert response.status_code == 200
        if "защищена от удаления" not in response.text or "TopicProgress object" in response.text:
            pytest.fail("Protected deletion did not preserve progress privacy", pytrace=False)
    assert Topic.objects.filter(pk=topic.pk).exists()
    assert TopicProgress.objects.filter(pk=mark.pk).exists()
