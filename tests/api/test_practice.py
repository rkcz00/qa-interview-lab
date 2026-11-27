from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta

import httpx
import pytest
from django.contrib.auth.models import Group
from django.db import models, transaction

from apps.accounts.models import User
from apps.assessments.models import Attempt, TopicProgress
from apps.assessments.attempts import build_snapshot
from apps.learning.models import Topic, TopicStatus
from apps.learning.tests.test_content import bilingual_topic
from apps.practice.models import PracticeSubmission, PracticeTask, PracticeTaskTranslation, SubmissionStatus, TopicPractice
from apps.practice.tests.factories import create_practice, write

from .pg_locks import wait_for_lock_waiters
from .test_attempts import correct_answers, incorrect_answers, data, post
from .test_catalog import publish, sign_in
from .test_content_admin import RevisionFields, admin_url, content_editor, csrf_header
from .test_content_admin import post as admin_post
from .test_content_admin import sign_in as admin_sign_in
from .test_registration import assert_error, bootstrap
from .test_session import TEST_PASSWORD


def preview_url(topic):
    return f"/api/v1/topics/{topic.pk}/practice/"


def start_url(topic):
    return preview_url(topic) + "submissions/"


def detail_url(identifier):
    return f"/api/v1/practice-submissions/{identifier}/"


def submit_url(identifier):
    return detail_url(identifier) + "submit/"


def delete_url(identifier):
    return detail_url(identifier) + "delete/"


def assert_public(payload, expected_fields):
    if set(payload) != set(expected_fields.split()):
        pytest.fail("Unexpected public Practice fields; payload suppressed", pytrace=False)


def pending(response, *, status=200, language="ru"):
    payload = data(response, status)
    assert_public(payload, "submission_id topic_id task_id status language task")
    assert payload["status"] == "in_progress" and payload["language"] == language
    assert isinstance(payload["submission_id"], str)
    assert_public(payload["task"], "practice_kind source_type title prompt source_text input_data environment output_spec normalization_mode answer_max_length")
    return payload


def submitted(response, verdict="correct"):
    payload = data(response)
    assert_public(payload, "submission_id topic_id task_id task_title status submitted_language submitted_at result")
    assert payload["status"] == "submitted"
    assert datetime.fromisoformat(payload["submitted_at"]).utcoffset() == timedelta(0)
    assert_public(payload["result"], "verdict")
    assert payload["result"]["verdict"] == verdict
    return payload


def unlock(client, topic):
    assert post(client, f"/api/v1/topics/{topic.pk}/read/", {}).status_code == 200
    attempt = data(post(client, f"/api/v1/topics/{topic.pk}/attempts/", {"language": "en"}), 201)
    assert post(client, f"/api/v1/attempts/{attempt['attempt_id']}/submit/", {"language": "en", "answers": incorrect_answers(attempt)}).status_code == 200


@pytest.fixture
def practice(api_client, bilingual_topic):
    user = User.objects.create_user("practice-learner@example.invalid", TEST_PASSWORD)
    task = create_practice(bilingual_topic)
    publish(bilingual_topic)
    sign_in(api_client, user)
    return api_client, user, bilingual_topic, task


@pytest.fixture
def started(practice):
    client, user, topic, task = practice
    unlock(client, topic)
    payload = pending(post(client, start_url(topic), {"language": "ru"}), status=201)
    return client, user, topic, task, payload["submission_id"]


def test_preview_is_readonly_public_localized_and_prerequisites_belong_to_current_user(practice):
    client, user, topic, _ = practice
    for language in ("ru", "en"):
        response = client.get(preview_url(topic), params={"language": language})
        payload = data(response)
        assert_public(payload, "topic_id task_id practice_kind language title can_start blocked_by normalization_mode answer_max_length")
        assert payload["title"] == f"{language} task"
        assert payload["language"] == language and payload["answer_max_length"] == 5000
        assert payload["can_start"] is False
        assert payload["blocked_by"] == ["article_not_read", "test_not_submitted"]
        assert "no-store" in response.headers["Cache-Control"]
    assert not PracticeSubmission.objects.exists()
    assert_error(post(client, start_url(topic), {"language": "ru"}), 403, "section_read_required")
    post(client, f"/api/v1/topics/{topic.pk}/read/", {})
    assert data(client.get(preview_url(topic)))["blocked_by"] == ["test_not_submitted"]
    attempt = data(post(client, f"/api/v1/topics/{topic.pk}/attempts/", {"language": "ru"}), 201)
    assert_error(post(client, start_url(topic), {"language": "en"}), 403, "practice_locked")
    post(client, f"/api/v1/attempts/{attempt['attempt_id']}/submit/", {"language": "en", "answers": incorrect_answers(attempt)})
    before = TopicProgress.objects.get(user=user, topic=topic).article_read_at
    assert data(client.get(preview_url(topic)))["can_start"] is True
    pending(post(client, start_url(topic), {"language": "en"}), status=201, language="en")
    assert TopicProgress.objects.get(user=user, topic=topic).article_read_at == before


def test_lifecycle_idempotency_language_and_public_result_are_exact(started):
    client, _, _, _, identifier = started
    for language in ("ru", "en"):
        payload = pending(client.get(detail_url(identifier), params={"language": language}), language=language)
        assert payload["task"]["title"] == f"{language} task"
    first = submitted(post(client, submit_url(identifier), {"language": "en", "answer_text": " text\r\n"}))
    assert first["task_title"] == "en task"
    again = submitted(post(client, submit_url(identifier), {"language": "en", "answer_text": "text"}))
    assert again == first
    assert data(client.get(detail_url(identifier), params={"language": "ru"})) == first
    for body in ({"language": "en", "answer_text": ""}, {"language": "en", "answer_text": "Text"}, {"language": "ru", "answer_text": "text"}):
        assert_error(post(client, submit_url(identifier), body), 409, "practice_already_submitted")
    assert_error(post(client, submit_url(identifier), {"language": "en", "answer_text": 42}), 400, "validation_error")
    assert PracticeSubmission.objects.count() == 1
    assert data(client.get(detail_url(identifier))) == first


@pytest.mark.parametrize("mode,expected,answer,verdict", [
    ("lf_trim_outer_v1", "text", "Text", "incorrect"),
    ("lf_trim_outer_v1", "", " \r\n", "correct"),
    ("lf_trim_outer_v1", "", "x", "incorrect"),
    ("lf_exact_v1", "", " ", "incorrect"),
    ("lf_exact_v1", " text\n", " text\r\n", "correct"),
    ("lf_exact_v1", "text", "text\n", "incorrect"),
], ids=["case", "empty-trimmed", "nonempty-vs-empty", "exact-space", "exact-crlf", "exact-newline"])
def test_comparison_modes_and_empty_references_over_tcp(practice, mode, expected, answer, verdict):
    client, _, topic, task = practice
    write(task, topic, expected_answer=expected, normalization_mode=mode)
    unlock(client, topic)
    identifier = pending(post(client, start_url(topic), {"language": "ru"}), status=201)["submission_id"]
    submitted(post(client, submit_url(identifier), {"language": "ru", "answer_text": answer}), verdict)


def test_invalid_payloads_do_not_complete_or_create_other_records(started):
    client, _, topic, _, identifier = started
    url = submit_url(identifier)
    values = [None, 42, 1.25, True, [], {}, "", " \r\n", "\0", "\ud800", "x" * 5001]
    for value in values:
        # ensure_ascii keeps a deliberately malformed scalar representable on the wire.
        import json
        response = client.post(url, content=json.dumps({"language": "ru", "answer_text": value}),
                               headers={**csrf_header(client), "Content-Type": "application/json"})
        assert_error(response, 400, "validation_error")
    for body in ({}, {"language": "ru"}, {"language": "de", "answer_text": "text"},
                 {"language": "ru", "answer_text": "text", "expected_answer": "text"}):
        assert_error(post(client, url, body), 400, "validation_error")
    assert_error(post(client, url + "?language=ru", {"language": "ru", "answer_text": "text"}), 400, "validation_error")
    assert_error(client.post(url, content="{", headers={**csrf_header(client), "Content-Type": "application/json"}), 400, "validation_error")
    assert_error(client.post(url, content="text", headers=csrf_header(client)), 415, "unsupported_media_type")
    for path in (preview_url(topic), detail_url(identifier)):
        for query in ("language=", "language=de", "language=ru&language=en", "unknown=1"):
            assert_error(client.get(path + "?" + query), 400, "validation_error")
    row = PracticeSubmission.objects.get(pk=identifier)
    assert row.status == SubmissionStatus.IN_PROGRESS and row.submitted_at is None
    assert PracticeSubmission.objects.count() == 1
    submitted(post(client, url, {"language": "ru", "answer_text": "text"}))


def test_raw_unicode_limit_and_safe_nonexecuting_answer(started):
    client, _, topic, task, identifier = started
    response = post(client, submit_url(identifier), {"language": "ru", "answer_text": "😀" * 5000})
    submitted(response, "incorrect")
    other = pending(post(client, start_url(topic), {"language": "ru"}), status=201)["submission_id"]
    submitted(post(client, submit_url(other), {"language": "ru", "answer_text": "raise RuntimeError('must never execute')"}), "incorrect")
    assert PracticeTask.objects.get(pk=task.pk).source_text == "print('text')"


@pytest.mark.parametrize("case", ["missing-cookie", "missing-header", "mismatch"])
def test_csrf_is_required_on_every_mutation_without_side_effects(started, case):
    client, _, topic, _, identifier = started
    for url, body in ((start_url(topic), {"language": "ru"}),
                      (submit_url(identifier), {"language": "ru", "answer_text": "text"}), (delete_url(identifier), {})):
        with httpx.Client(base_url=client.base_url, trust_env=False) as other:
            other.cookies.update(client.cookies)
            headers = csrf_header(client)
            if case == "missing-cookie":
                other.cookies.delete("csrftoken")
            elif case == "missing-header":
                headers = {}
            else:
                token = headers["X-CSRFToken"]
                headers = {"X-CSRFToken": ("A" if token[0] != "A" else "B") + token[1:]}
            assert_error(other.post(url, json=body, headers=headers), 403, "csrf_failed")
    assert PracticeSubmission.objects.count() == 1
    assert PracticeSubmission.objects.get(pk=identifier).status == SubmissionStatus.IN_PROGRESS


def test_anonymous_and_unsupported_methods_follow_existing_contract(started):
    client, _, topic, _, identifier = started
    with httpx.Client(base_url=client.base_url, trust_env=False) as anonymous:
        bootstrap(anonymous)
        for url in (preview_url(topic), detail_url(identifier)):
            assert_error(anonymous.get(url), 403, "authentication_required")
        for url, body in ((start_url(topic), {"language": "ru"}), (submit_url(identifier), {"language": "ru", "answer_text": "text"}), (delete_url(identifier), {})):
            assert_error(post(anonymous, url, body), 403, "authentication_required")
    for url in (start_url(topic), submit_url(identifier), delete_url(identifier)):
        response = client.get(url)
        assert_error(response, 405, "method_not_allowed")
        assert response.headers["Allow"] == "POST"
    for url in (preview_url(topic), detail_url(identifier)):
        response = post(client, url, {})
        assert_error(response, 405, "method_not_allowed")
        assert response.headers["Allow"] == "GET"
    assert_error(client.delete(delete_url(identifier), headers=csrf_header(client)), 405, "method_not_allowed")


@pytest.mark.parametrize("role", ["learner", "content-admin", "superuser"])
def test_ownership_is_enforced_before_query_payload_or_idempotency(started, role):
    client, owner, topic, _, identifier = started
    submitted(post(client, submit_url(identifier), {"language": "ru", "answer_text": "text"}))
    second = User.objects.create_user(f"practice-other-{role}@example.invalid", TEST_PASSWORD,
                                      is_staff=role != "learner", is_superuser=role == "superuser")
    assert second.pk != owner.pk
    if role == "content-admin":
        second.groups.add(Group.objects.get(name="Content Admin"))
    with httpx.Client(base_url=client.base_url, trust_env=False) as other:
        sign_in(other, second)
        assert_error(other.get(detail_url(identifier) + "?language=invalid"), 404, "not_found")
        for url in (submit_url(identifier), delete_url(identifier)):
            assert_error(other.post(url, content="{", headers={**csrf_header(other), "Content-Type": "application/json"}), 404, "not_found")
        assert data(other.get(preview_url(topic)))["blocked_by"] == ["article_not_read", "test_not_submitted"]
        assert_error(post(other, start_url(topic), {"language": "ru"}), 403, "section_read_required")
    assert PracticeSubmission.objects.count() == 1


@pytest.mark.parametrize("resource", ["topic", "task"])
def test_snapshot_survives_edit_and_unpublish_and_new_access_is_hidden(started, resource):
    client, _, topic, task, identifier = started
    before = deepcopy(PracticeSubmission.objects.get(pk=identifier).task_snapshot)
    old_ru = pending(client.get(detail_url(identifier)))
    old_en = pending(client.get(detail_url(identifier), params={"language": "en"}), language="en")
    write(task, topic, expected_answer="updated", source_text="print('updated')", normalization_mode="lf_exact_v1")
    write(task.translations.get(language="en"), topic, title="Updated title")
    if resource == "task":
        write(task, topic, status=TopicStatus.DRAFT)
    else:
        topic.status = TopicStatus.DRAFT
        topic.save(update_fields=("status",))
    for path in (preview_url(topic), start_url(topic)):
        response = client.get(path) if path == preview_url(topic) else post(client, path, {"language": "ru"})
        assert_error(response, 404, "not_found")
    assert pending(client.get(detail_url(identifier))) == old_ru
    assert pending(client.get(detail_url(identifier), params={"language": "en"}), language="en") == old_en
    first = submitted(post(client, submit_url(identifier), {"language": "en", "answer_text": " text\r\n"}))
    assert first["task_title"] == "en task"
    if PracticeSubmission.objects.get(pk=identifier).task_snapshot != before:
        pytest.fail("Stored snapshot changed after source edit", pytrace=False)
    assert data(client.get(detail_url(identifier))) == first


def test_complete_published_edit_allows_new_snapshot_and_preserves_old_one(started):
    client, _, topic, task, old_id = started
    old_payload = pending(client.get(detail_url(old_id)))
    write(task, topic, expected_answer="updated", source_text="print('updated')")
    new_payload = pending(post(client, start_url(topic), {"language": "en"}), status=201, language="en")
    assert new_payload["submission_id"] != old_id
    assert pending(client.get(detail_url(old_id))) == old_payload
    assert new_payload["task"]["source_text"] == "print('updated')"
    submitted(post(client, submit_url(old_id), {"language": "ru", "answer_text": "text"}))
    submitted(post(client, submit_url(new_payload["submission_id"]), {"language": "en", "answer_text": "updated"}))


def test_submitted_test_alone_does_not_replace_read_and_historical_test_remains_valid(practice):
    client, user, topic, task = practice
    # Historical work remains submittable without inventing a fresh start before Read.
    old = Attempt.objects.create(user=user, topic=topic, content_snapshot=build_snapshot(topic))
    quiz = data(client.get(f"/api/v1/attempts/{old.pk}/"))
    post(client, f"/api/v1/attempts/{quiz['attempt_id']}/submit/", {"language": "ru", "answers": incorrect_answers(quiz)})
    assert data(client.get(preview_url(topic)))["blocked_by"] == ["article_not_read"]
    assert_error(post(client, start_url(topic), {"language": "ru"}), 403, "section_read_required")
    write(task, topic, source_text="print('text') # revised content")
    post(client, f"/api/v1/topics/{topic.pk}/read/", {})
    pending(post(client, start_url(topic), {"language": "en"}), status=201, language="en")


def test_absent_configuration_missing_ids_and_draft_content_return_404(practice):
    client, _, topic, task = practice
    for identifier in ("0", "01", "-1", "invalid", str(2**63), str(2**62)):
        assert_error(client.get(detail_url(identifier)), 404, "not_found")
        assert_error(post(client, submit_url(identifier), {}), 404, "not_found")
        assert_error(post(client, delete_url(identifier), {}), 404, "not_found")
    write(task, topic, status=TopicStatus.DRAFT)
    assert_error(client.get(preview_url(topic)), 404, "not_found")
    assert_error(post(client, start_url(topic), {"language": "ru"}), 404, "not_found")
    task.delete(expected_revision=topic.revision)
    assert_error(client.get(preview_url(topic)), 404, "not_found")
    topic.refresh_from_db()
    topic.practice.delete(expected_revision=topic.revision)
    assert_error(client.get(preview_url(topic)), 404, "not_found")


def test_owner_delete_removes_whole_work_and_preserves_read_test_and_mastery(started):
    client, user, topic, _, identifier = started
    before_progress = data(client.get("/api/v1/progress/"))
    before_attempts = data(client.get("/api/v1/attempts/"))
    read_at = TopicProgress.objects.get(user=user, topic=topic).article_read_at
    submitted(post(client, submit_url(identifier), {"language": "ru", "answer_text": "text"}))
    assert data(client.get("/api/v1/progress/")) == before_progress
    assert_error(post(client, delete_url(identifier), {"user_id": str(user.pk)}), 400, "validation_error")
    response = post(client, delete_url(identifier), {})
    assert response.status_code == 204 and response.content == b""
    assert not PracticeSubmission.objects.filter(pk=identifier).exists()
    assert_error(client.get(detail_url(identifier)), 404, "not_found")
    assert_error(post(client, submit_url(identifier), {"language": "ru", "answer_text": "text"}), 404, "not_found")
    assert_error(post(client, delete_url(identifier), {}), 404, "not_found")
    assert data(client.get("/api/v1/progress/")) == before_progress
    assert data(client.get("/api/v1/attempts/")) == before_attempts
    assert TopicProgress.objects.get(user=user, topic=topic).article_read_at == read_at


def test_incorrect_or_deleted_practice_does_not_revoke_existing_mastery(started):
    client, _, topic, _, identifier = started
    quiz = data(post(client, f"/api/v1/topics/{topic.pk}/attempts/", {"language": "ru"}), 201)
    post(client, f"/api/v1/attempts/{quiz['attempt_id']}/submit/", {"language": "ru", "answers": correct_answers(quiz)})
    before = data(client.get("/api/v1/progress/"))
    assert before[0]["mastered"] is True
    submitted(post(client, submit_url(identifier), {"language": "en", "answer_text": "wrong"}), "incorrect")
    assert data(client.get("/api/v1/progress/")) == before
    assert post(client, delete_url(identifier), {}).status_code == 204
    assert data(client.get("/api/v1/progress/")) == before


@pytest.mark.parametrize("same_payload", [True, False], ids=["equivalent", "different"])
def test_concurrent_submit_commits_only_one_result(started, same_payload):
    client, user, _, _, identifier = started
    with httpx.Client(base_url=client.base_url, trust_env=False) as other:
        sign_in(other, user)
        with ThreadPoolExecutor(max_workers=2) as pool:
            with transaction.atomic():
                PracticeSubmission.objects.select_for_update().get(pk=identifier)
                first = pool.submit(post, client, submit_url(identifier), {"language": "ru", "answer_text": "text"})
                wait_for_lock_waiters("practice_practicesubmission", 1)
                second = pool.submit(post, other, submit_url(identifier), {"language": "ru", "answer_text": " text\r\n" if same_payload else "different"})
                wait_for_lock_waiters(User._meta.db_table, 1)
                wait_for_lock_waiters("practice_practicesubmission", 1)
            first_result = submitted(first.result(timeout=15))
            second_response = second.result(timeout=15)
            if same_payload:
                assert submitted(second_response) == first_result
            else:
                assert_error(second_response, 409, "practice_already_submitted")
    assert PracticeSubmission.objects.count() == 1
    assert data(client.get(detail_url(identifier))) == first_result


@pytest.mark.parametrize("delete_first", [False, True], ids=["submit-first", "delete-first"])
def test_concurrent_submit_delete_never_resurrects_a_work(started, delete_first):
    client, user, _, _, identifier = started
    with httpx.Client(base_url=client.base_url, trust_env=False) as other:
        sign_in(other, user)
        operations = [(submit_url(identifier), {"language": "ru", "answer_text": "text"}), (delete_url(identifier), {})]
        if delete_first:
            operations.reverse()
        with ThreadPoolExecutor(max_workers=2) as pool:
            with transaction.atomic():
                PracticeSubmission.objects.select_for_update().get(pk=identifier)
                first = pool.submit(post, client, *operations[0])
                wait_for_lock_waiters("practice_practicesubmission", 1)
                second = pool.submit(post, other, *operations[1])
                wait_for_lock_waiters(User._meta.db_table, 1)
                wait_for_lock_waiters("practice_practicesubmission", 1)
            assert first.result(timeout=15).status_code == (204 if delete_first else 200)
            assert second.result(timeout=15).status_code == (404 if delete_first else 204)
    assert not PracticeSubmission.objects.filter(pk=identifier).exists()


def test_start_waits_for_atomic_unpublish_before_snapshot(practice):
    client, _, topic, _ = practice
    unlock(client, topic)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            locked = Topic.objects.select_for_update().get(pk=topic.pk)
            started = pool.submit(post, client, start_url(topic), {"language": "ru"})
            wait_for_lock_waiters("learning_topic", 1)
            locked.status = TopicStatus.DRAFT
            locked.save(update_fields=("status",))
        assert_error(started.result(timeout=15), 404, "not_found")
    assert not PracticeSubmission.objects.exists()


def test_start_waits_for_complete_published_edit_and_captures_one_consistent_revision(practice):
    client, _, topic, task = practice
    unlock(client, topic)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            Topic.objects.select_for_update().get(pk=topic.pk)
            started = pool.submit(post, client, start_url(topic), {"language": "ru"})
            wait_for_lock_waiters("learning_topic", 1)
            write(task, topic, expected_answer="updated", source_text="print('updated')")
        payload = pending(started.result(timeout=15), status=201)
    row = PracticeSubmission.objects.get(pk=payload["submission_id"])
    assert row.task_snapshot["source_revision"] == topic.revision
    assert payload["task"]["source_text"] == "print('updated')"
    submitted(post(client, submit_url(row.pk), {"language": "ru", "answer_text": "updated"}))


def test_unexpected_snapshot_failure_is_safe_500_and_submission_rolls_back(started):
    client, _, _, _, identifier = started
    row = PracticeSubmission.objects.get(pk=identifier)
    row.task_snapshot = {"normalization_mode": "unsupported-version"}
    models.Model.save(row, update_fields=("task_snapshot",))
    assert_error(post(client, submit_url(identifier), {"language": "ru", "answer_text": "text"}), 500, "internal_error")
    assert PracticeSubmission.objects.get(pk=identifier).status == SubmissionStatus.IN_PROGRESS


def test_content_admin_can_create_edit_publish_only_the_three_new_content_models(api_client, bilingual_topic):
    client = api_client
    admin_sign_in(client, content_editor("practice-editor"))
    topic = bilingual_topic
    practice_url = admin_url(TopicPractice, "add")
    assert f"{topic.pk}:{topic.revision}" in RevisionFields(client.get(practice_url)).options
    assert admin_post(client, practice_url, {"topic": f"{topic.pk}:{topic.revision}", "practice_kind": "single_correct_answer"}).status_code == 302
    config = TopicPractice.objects.get(topic=topic)
    topic.refresh_from_db()
    assert admin_post(client, admin_url(PracticeTask, "add"), {
        "topic_practice": f"{config.pk}:{topic.revision}", "source_type": "python", "source_text": "print('text')",
        "input_data": "", "environment": "Python 3.14.2", "output_spec": "stdout text", "expected_answer": "text",
        "normalization_mode": "lf_trim_outer_v1",
    }).status_code == 302
    task = PracticeTask.objects.get(topic_practice=config)
    for language in ("ru", "en"):
        topic.refresh_from_db()
        assert admin_post(client, admin_url(PracticeTaskTranslation, "add"), {
            "task": f"{task.pk}:{topic.revision}", "language": language, "title": f"{language} task", "prompt": f"{language} prompt",
        }).status_code == 302
    index = client.get("/admin/")
    for model in (TopicPractice, PracticeTask, PracticeTaskTranslation):
        assert admin_url(model, "changelist") in index.text
        assert client.get(admin_url(model, "changelist")).status_code == 200
        assert client.get(admin_url(model, "change", model.objects.first())).status_code == 200
    topic.refresh_from_db()
    action = {"action": "publish_selected", "_selected_action": [str(task.pk)], "index": "0"}
    confirmation = admin_post(client, admin_url(PracticeTask, "changelist"), action)
    assert RevisionFields(confirmation).revisions == [f"{topic.pk}:{topic.revision}"]
    action.update(confirm="yes", confirm_expected="yes", expected_revision=[f"{topic.pk}:{topic.revision}"])
    assert admin_post(client, admin_url(PracticeTask, "changelist"), action).status_code == 302
    task.refresh_from_db()
    assert task.status == TopicStatus.PUBLISHED
    stale = admin_post(client, admin_url(PracticeTask, "changelist"), action)
    assert stale.status_code == 409 and 'data-error-code="edit_conflict"' in stale.text
    for model_name in ("practicesubmission",):
        for path in (f"/admin/practice/{model_name}/", f"/admin/practice/{model_name}/1/change/"):
            assert client.get(path).status_code == 404
    assert not User.objects.get(email="practice-editor@example.invalid").has_perm("practice.view_practicesubmission")


def test_concurrent_admin_child_edits_preserve_first_version_and_reject_stale_revision(practice):
    client, _, topic, task = practice
    editor = content_editor("practice-concurrent-editor")
    admin_sign_in(client, editor)
    translation = task.translations.get(language="en")
    url = admin_url(PracticeTaskTranslation, "change", translation)
    body = {"expected_revision": str(topic.revision), "language": "en", "title": "en task", "prompt": "First version"}
    initial_revision = topic.revision
    with httpx.Client(base_url=client.base_url, trust_env=False) as other:
        admin_sign_in(other, editor)
        with ThreadPoolExecutor(max_workers=2) as pool:
            with transaction.atomic():
                Topic.objects.select_for_update().get(pk=topic.pk)
                first = pool.submit(admin_post, client, url, body)
                wait_for_lock_waiters("learning_topic", 1)
                second = pool.submit(admin_post, other, url, {**body, "prompt": "Second version"})
                wait_for_lock_waiters("learning_topic", 2)
            assert first.result(timeout=15).status_code == 302
            rejected = second.result(timeout=15)
            assert rejected.status_code == 409 and 'data-error-code="edit_conflict"' in rejected.text
    translation.refresh_from_db()
    topic.refresh_from_db()
    assert translation.prompt == "First version" and topic.revision == initial_revision + 1


def test_admin_incomplete_publish_and_published_edit_roll_back_entire_operation(practice):
    client, _, topic, task = practice
    admin_sign_in(client, content_editor("practice-atomic-editor"))
    translation = task.translations.get(language="en")
    before = topic.revision
    rejected = admin_post(client, admin_url(PracticeTaskTranslation, "change", translation), {
        "expected_revision": before, "language": "en", "title": "Changed title", "prompt": "",
    })
    assert rejected.status_code == 400 and 'data-error-code="incomplete_content"' in rejected.text
    translation.refresh_from_db()
    topic.refresh_from_db()
    assert translation.title == "en task" and translation.prompt == "en prompt" and topic.revision == before
    write(task, topic, status=TopicStatus.DRAFT)
    write(translation, topic, prompt="")
    before = topic.revision
    action = {"action": "publish_selected", "_selected_action": [str(task.pk)], "confirm": "yes",
              "confirm_expected": "yes", "expected_revision": [f"{topic.pk}:{before}"]}
    rejected = admin_post(client, admin_url(PracticeTask, "changelist"), action)
    assert rejected.status_code == 400 and 'data-error-code="incomplete_content"' in rejected.text
    task.refresh_from_db()
    topic.refresh_from_db()
    assert task.status == TopicStatus.DRAFT and topic.revision == before
