from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
from uuid import uuid4

import httpx
import pytest
from django.db import transaction
from django.db import models

from apps.accounts.models import User
from apps.assessments.models import Attempt, TopicProgress, TopicSectionProgress, UserProgressState
from apps.learning.models import Topic, TopicStatus
from apps.learning.tests.test_content import bilingual_topic
from apps.learning.tests.test_sections import add_section
from apps.practice.models import PracticeSubmission
from apps.practice.tests.factories import create_practice

from .pg_locks import wait_for_lock_waiters
from .test_attempts import correct_answers, data, learner, post, start_url, submit_url
from .test_catalog import publish, sign_in
from .test_content_admin import csrf_header
from .test_progress import store_historical_result
from .test_registration import assert_error, bootstrap
from .test_session import TEST_PASSWORD
from .test_content_admin import admin_url, editor


def reading_url(topic_id):
    return f"/api/v1/topics/{topic_id}/reading/"


def section_url(topic_id, section_id):
    return f"/api/v1/topics/{topic_id}/sections/{section_id}/"


def mark_url(topic_id, section_id):
    return section_url(topic_id, section_id) + "read/"


def assert_public(value):
    forbidden = {"user_id", "expected_answer", "is_correct", "revision", "expected_revision", "server_key",
                 "content_snapshot", "task_snapshot", "submitted_answers", "submitted_answer", "password", "session_id"}
    if isinstance(value, dict):
        assert not forbidden.intersection(value)
        for item in value.values():
            assert_public(item)
    elif isinstance(value, list):
        for item in value:
            assert_public(item)


def test_section_progress_anonymous_is_denied_with_safe_envelope(api_client):
    for path in (reading_url(1), section_url(1, 1)):
        assert_error(api_client.get(path), 403, "authentication_required")
    token = bootstrap(api_client)
    response = api_client.post(mark_url(1, 1), json={}, headers={"X-CSRFToken": token, "X-Progress-Generation": "1"})
    assert_error(response, 403, "authentication_required")
    assert not TopicSectionProgress.objects.exists()


def test_corrupt_published_topic_without_sections_is_a_safe_server_error(learner, bilingual_topic):
    client, _ = learner
    topic = bilingual_topic
    create_practice(topic)
    publish(topic)
    # Only a corruption fixture bypasses the content operation's publication rule.
    models.Model.delete(topic.sections.get())
    for response in (
        client.get(reading_url(topic.pk)),
        client.get("/api/v1/completion-progress/"),
        post(client, f"/api/v1/topics/{topic.pk}/read/", {}),
        post(client, start_url(topic.pk), {"language": "ru"}),
        post(client, f"/api/v1/topics/{topic.pk}/practice/submissions/", {"language": "ru"}),
    ):
        assert_error(response, 500, "internal_error")
        assert_public(data_error := response.json())
        assert "traceback" not in json.dumps(data_error).lower()
    assert not TopicSectionProgress.objects.exists() and not Attempt.objects.exists() and not PracticeSubmission.objects.exists()


def test_reading_and_section_details_have_exact_ordered_ru_en_projection(learner, bilingual_topic):
    client, user = learner
    topic = bilingual_topic
    first = add_section(topic, position=5)
    hidden = add_section(topic, position=30, status="draft", languages=("ru",))
    publish(topic)
    before = TopicSectionProgress.objects.count()
    for language in ("ru", "en"):
        response = client.get(reading_url(topic.pk), params={"language": language})
        summary = data(response)
        assert set(summary) == {"topic_id", "title", "language", "progress_generation", "reading", "sections"}
        assert summary["title"] == language + " title" and summary["language"] == language
        assert summary["progress_generation"] == "1"
        assert [item["position"] for item in summary["sections"]] == [5, 10]
        assert all(set(item) == {"section_id", "position", "title", "read_at"} for item in summary["sections"])
        detail = data(client.get(section_url(topic.pk, first.pk), params={"language": language}))
        assert set(detail) == {"topic_id", "topic_title", "language", "progress_generation", "section",
                               "previous_section_id", "next_section_id", "reading"}
        assert set(detail["section"]) == {"section_id", "position", "title", "article_body", "read_at"}
        assert detail["section"]["article_body"] == f"  {language} body 5\r\n\n"
        assert detail["previous_section_id"] is None and detail["next_section_id"] == str(topic.sections.get(position=10).pk)
        assert detail["reading"] == {"total_sections": 2, "read_sections": 0, "is_read": False, "completion_contribution": 0}
        assert "no-store" in response.headers["Cache-Control"] and "Cookie" in response.headers["Vary"]
        assert_public(summary)
        assert_public(detail)
    assert TopicSectionProgress.objects.count() == before
    assert not UserProgressState.objects.exists()
    assert_error(client.get(section_url(topic.pk, hidden.pk)), 404, "not_found")


def test_partial_read_legacy_gate_new_section_and_old_attempt_snapshot(learner, bilingual_topic):
    client, user = learner
    topic = bilingual_topic
    first = topic.sections.get()
    second = add_section(topic)
    publish(topic)
    assert_error(post(client, start_url(topic.pk), {"language": "ru"}), 403, "section_read_required")
    assert_error(post(client, f"/api/v1/topics/{topic.pk}/read/", {}), 403, "section_read_required")
    assert not Attempt.objects.exists() and not TopicSectionProgress.objects.exists()
    marked = data(post(client, mark_url(topic.pk, first.pk), {}))
    assert set(marked) == {"topic_id", "section_id", "read_at", "progress_generation", "reading"}
    assert marked["reading"] == {"total_sections": 2, "read_sections": 1, "is_read": False, "completion_contribution": 15}
    assert datetime.fromisoformat(marked["read_at"]).utcoffset() == timedelta(0)
    assert data(post(client, mark_url(topic.pk, first.pk), {})) == marked
    assert data(client.get("/api/v1/progress/"))[0]["article_read_at"] is None
    assert_error(post(client, start_url(topic.pk), {"language": "en"}), 403, "section_read_required")
    last = data(post(client, mark_url(topic.pk, second.pk), {}))
    assert last["reading"]["is_read"] and last["reading"]["completion_contribution"] == 30
    assert_error(post(client, f"/api/v1/topics/{topic.pk}/read/", {}), 403, "section_read_required")
    pending = data(post(client, start_url(topic.pk), {"language": "en"}), 201)
    third = add_section(topic, position=40)
    assert_error(post(client, start_url(topic.pk), {"language": "ru"}), 403, "section_read_required")
    assert Attempt.objects.filter(user=user).count() == 1
    assert data(client.get(f"/api/v1/attempts/{pending['attempt_id']}/?language=en")) == pending
    body = {"language": "en", "answers": correct_answers(pending)}
    saved = data(post(client, submit_url(pending["attempt_id"]), body))
    assert data(post(client, submit_url(pending["attempt_id"]), body)) == saved
    completion = data(client.get("/api/v1/completion-progress/"))["topics"][0]
    assert not completion["mastered"] and completion["completion_progress"] == 90
    data(post(client, mark_url(topic.pk, third.pk), {}))
    assert data(client.get("/api/v1/completion-progress/"))["topics"][0]["mastered"]
    assert TopicSectionProgress.objects.get(user=user, section=first).read_at == datetime.fromisoformat(marked["read_at"])
    assert_public(saved)


@pytest.mark.parametrize("missing", ["cookie", "header", "mismatch"])
def test_section_read_rejects_csrf_without_creating_any_progress(learner, bilingual_topic, missing):
    client, _ = learner
    topic = bilingual_topic
    publish(topic)
    headers = csrf_header(client)
    if missing == "cookie":
        client.cookies.delete("csrftoken")
    elif missing == "header":
        headers.pop("X-CSRFToken")
    else:
        headers["X-CSRFToken"] = "x" * 64
    assert_error(client.post(mark_url(topic.pk, topic.sections.get().pk), json={}, headers=headers), 403, "csrf_failed")
    assert not TopicSectionProgress.objects.exists() and not TopicProgress.objects.exists()


@pytest.mark.parametrize("query", ["language=", "language=de", "language=ru&language=en", "extra=1"])
def test_new_reading_get_rejects_unsupported_query(learner, bilingual_topic, query):
    client, _ = learner
    topic = bilingual_topic
    publish(topic)
    for path in (reading_url(topic.pk), section_url(topic.pk, topic.sections.get().pk)):
        assert_error(client.get(path + "?" + query), 400, "validation_error")


def test_section_belongs_to_topic_and_draft_lookup_precedes_payload_generation(learner, bilingual_topic):
    client, _ = learner
    topic = bilingual_topic
    original = topic.sections.get()
    foreign_topic = Topic.objects.create()
    foreign = add_section(foreign_topic)
    publish(topic)
    for section_id in (foreign.pk, 0, "invalid", 2**64):
        path = section_url(topic.pk, section_id)
        assert_error(client.get(path + "?language=de"), 404, "not_found")
        assert_error(client.post(path + "read/", content="not json", headers=csrf_header(client, progress_generation=None)), 404, "not_found")
    topic.refresh_from_db()
    topic.status = TopicStatus.DRAFT
    topic.save()
    assert_error(client.get(reading_url(topic.pk) + "?language=de"), 404, "not_found")
    assert_error(post(client, mark_url(topic.pk, original.pk), {}), 404, "not_found")
    assert not TopicSectionProgress.objects.exists()


@pytest.mark.parametrize("payload", [None, [], 42, {"user_id": "1"}, {"read_at": "2026-01-01T00:00:00Z"}, {"language": "ru"}])
def test_section_read_accepts_only_empty_object(learner, bilingual_topic, payload):
    client, _ = learner
    topic = bilingual_topic
    publish(topic)
    response = client.post(mark_url(topic.pk, topic.sections.get().pk), content=json.dumps(payload),
                           headers={**csrf_header(client), "Content-Type": "application/json"})
    assert_error(response, 400, "validation_error")
    assert not TopicSectionProgress.objects.exists()


def test_two_concurrent_section_reads_keep_one_row_and_the_first_date(learner, bilingual_topic):
    client, user = learner
    topic = bilingual_topic
    publish(topic)
    url = mark_url(topic.pk, topic.sections.get().pk)
    headers = csrf_header(client)
    with httpx.Client(base_url=str(client.base_url), cookies=client.cookies, timeout=15) as other:
        with ThreadPoolExecutor(max_workers=2) as pool:
            with transaction.atomic():
                User.objects.select_for_update().get(pk=user.pk)
                first = pool.submit(client.post, url, json={}, headers=headers)
                second = pool.submit(other.post, url, json={}, headers=headers)
                wait_for_lock_waiters("accounts_user", 2)
            assert data(first.result(timeout=15)) == data(second.result(timeout=15))
    assert TopicSectionProgress.objects.filter(user=user).count() == 1


def test_other_users_marks_cannot_satisfy_read_or_be_overwritten(learner, bilingual_topic):
    client, owner = learner
    topic = bilingual_topic
    publish(topic)
    section = topic.sections.get()
    first = data(post(client, mark_url(topic.pk, section.pk), {}))
    other = User.objects.create_user("section-foreign@example.invalid", TEST_PASSWORD)
    with httpx.Client(base_url=str(client.base_url), timeout=15) as foreign:
        sign_in(foreign, other)
        assert data(foreign.get(reading_url(topic.pk)))["reading"]["read_sections"] == 0
        assert_error(post(foreign, start_url(topic.pk), {"language": "ru"}), 403, "section_read_required")
        assert_error(post(foreign, mark_url(topic.pk, section.pk), {"user_id": str(owner.pk)}), 400, "validation_error")
        data(post(foreign, mark_url(topic.pk, section.pk), {}))
    assert TopicSectionProgress.objects.filter(section=section).count() == 2
    assert TopicSectionProgress.objects.get(user=owner).read_at == datetime.fromisoformat(first["read_at"])


def test_practice_start_uses_all_sections_not_legacy_or_foreign_marks(learner, bilingual_topic):
    client, user = learner
    topic = bilingual_topic
    task = create_practice(topic)
    first = topic.sections.get()
    second = add_section(topic)
    publish(topic)
    TopicProgress.objects.create(user=user, topic=topic)
    store_historical_result(user, topic, 0, 2)
    path = f"/api/v1/topics/{topic.pk}/practice/submissions/"
    assert_error(post(client, path, {"language": "ru"}), 403, "section_read_required")
    data(post(client, mark_url(topic.pk, first.pk), {}))
    assert_error(post(client, path, {"language": "en"}), 403, "section_read_required")
    data(post(client, mark_url(topic.pk, second.pk), {}))
    pending = data(post(client, path, {"language": "en"}), 201)
    add_section(topic, position=40)
    assert_error(post(client, path, {"language": "ru"}), 403, "section_read_required")
    assert PracticeSubmission.objects.filter(user=user).count() == 1
    result = data(post(client, f"/api/v1/practice-submissions/{pending['submission_id']}/submit/",
                       {"language": "en", "answer_text": "text"}))
    assert result["result"] == {"verdict": "correct"}
    assert_public(result)
    assert task.pk == int(result["task_id"])


@pytest.mark.parametrize("first_operation", ["read", "reset"])
def test_reset_serializes_with_section_read_and_rejects_late_writes(learner, bilingual_topic, first_operation):
    client, user = learner
    topic = bilingual_topic
    publish(topic)
    section = topic.sections.get()
    url = mark_url(topic.pk, section.pk)
    body = {"confirmation": "reset_all_progress", "request_id": str(uuid4())}
    headers = csrf_header(client)
    with httpx.Client(base_url=str(client.base_url), cookies=client.cookies, timeout=15) as other:
        with ThreadPoolExecutor(max_workers=2) as pool:
            with transaction.atomic():
                if first_operation == "read":
                    Topic.objects.select_for_update().get(pk=topic.pk)
                    reading = pool.submit(client.post, url, json={}, headers=headers)
                    wait_for_lock_waiters("learning_topic", 1)
                    resetting = pool.submit(other.post, "/api/v1/progress/reset/", json=body, headers=headers)
                    wait_for_lock_waiters("accounts_user", 1)
                else:
                    User.objects.select_for_update().get(pk=user.pk)
                    resetting = pool.submit(other.post, "/api/v1/progress/reset/", json=body, headers=headers)
                    wait_for_lock_waiters("accounts_user", 1)
                    reading = pool.submit(client.post, url, json={}, headers=headers)
                    wait_for_lock_waiters("accounts_user", 2)
            assert data(resetting.result(timeout=15)) == {"progress_generation": "2"}
            response = reading.result(timeout=15)
            if first_operation == "read":
                assert response.status_code == 200
            else:
                assert_error(response, 409, "progress_reset")
    assert not TopicSectionProgress.objects.exists() and not TopicProgress.objects.exists()
    assert UserProgressState.objects.get(user=user).generation == 2
    assert data(client.get(section_url(topic.pk, section.pk)))["section"]["read_at"] is None
    assert_error(post(client, url, {}), 409, "progress_reset")


def test_content_admin_cannot_see_section_progress_or_its_protected_owners(editor, bilingual_topic):
    topic = bilingual_topic
    section = topic.sections.get()
    owner = User.objects.create_user("private-section-owner@example.invalid")
    mark = TopicSectionProgress.objects.create(user=owner, section=section)
    assert editor.get("/admin/assessments/topicsectionprogress/").status_code == 404
    assert editor.get(f"/admin/assessments/topicsectionprogress/{mark.pk}/change/").status_code == 404
    index = editor.get("/admin/")
    assert "topicsectionprogress" not in index.text.lower()
    for obj in (section, topic):
        path = admin_url(type(obj), "delete", obj)
        response = editor.get(path)
        assert response.status_code == 200
        assert owner.email not in response.text
        assert f"TopicSectionProgress object ({mark.pk})" not in response.text
        assert "Запись связана с сохранёнными данными и защищена от удаления." in response.text
        rejected = editor.post(path, data={"post": "yes", "expected_revision": topic.revision}, headers=csrf_header(editor))
        assert rejected.status_code == 200
        assert TopicSectionProgress.objects.filter(pk=mark.pk).exists()
    assert Topic.objects.filter(pk=topic.pk).exists()
