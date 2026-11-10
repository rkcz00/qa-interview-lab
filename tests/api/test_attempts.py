from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import httpx
import pytest
from django.contrib.auth.models import Group
from django.db import transaction

from apps.accounts.models import User
from apps.assessments.models import Attempt, AttemptStatus, ChoiceTranslation, QuestionTranslation, QuestionType
from apps.learning.changes import edit_topics
from apps.learning.models import Language, Topic, TopicStatus
from apps.learning.tests.test_content import bilingual_topic

from .pg_locks import wait_for_lock_waiters
from .test_catalog import publish, sign_in
from .test_content_admin import admin_url, content_editor, csrf_header
from .test_content_admin import sign_in as sign_in_admin
from .test_registration import assert_error, bootstrap
from .test_session import TEST_PASSWORD


ATTEMPTS_URL = "/api/v1/attempts/"


def start_url(topic_id):
    return f"/api/v1/topics/{topic_id}/attempts/"


def attempt_url(attempt_id):
    return f"{ATTEMPTS_URL}{attempt_id}/"


def submit_url(attempt_id):
    return f"{attempt_url(attempt_id)}submit/"


def post(client, url, payload):
    return client.post(url, json=payload, headers=csrf_header(client), timeout=15)


def data(response, status=200):
    assert response.status_code == status
    payload = response.json()
    if set(payload) != {"data"}:
        pytest.fail("Unexpected attempt response envelope", pytrace=False)
    return payload["data"]


@pytest.fixture
def learner(api_client):
    user = User.objects.create_user("attempt-owner@example.invalid", TEST_PASSWORD)
    sign_in(api_client, user)
    return api_client, user


def start(client, topic, language="ru"):
    return data(post(client, start_url(topic.pk), {"language": language}), status=201)


def answer(question_id, *choice_ids):
    return {"question_id": question_id, "choice_ids": list(choice_ids)}


def correct_answers(pending):
    answers = []
    for question in pending["questions"]:
        positions = {10} if question["question_type"] == QuestionType.SINGLE_CHOICE else {10, 20}
        choices = [choice["choice_id"] for choice in question["choices"] if choice["position"] in positions]
        answers.append(answer(question["question_id"], *choices))
    return answers


def assert_pending(payload, topic, language):
    questions = [
        {
            "question_id": str(question.pk),
            "position": question.position,
            "question_type": question.question_type,
            "text": question.translations.get(language=language).text,
            "choices": [
                {
                    "choice_id": str(choice.pk),
                    "position": choice.position,
                    "text": choice.translations.get(language=language).text,
                }
                for choice in question.choices.all()
            ],
        }
        for question in topic.questions.all()
    ]
    if payload != {
        "attempt_id": payload.get("attempt_id"),
        "topic_id": str(topic.pk),
        "status": "in_progress",
        "language": language,
        "questions": questions,
    }:
        pytest.fail("Pending attempt did not match the public question schema", pytrace=False)
    assert isinstance(payload["attempt_id"], str)


def assert_submitted(payload, attempt_id, topic_id, language, correct_count, total_count, percentage):
    submitted_at = payload.get("submitted_at")
    assert isinstance(submitted_at, str)
    assert datetime.fromisoformat(submitted_at).utcoffset() == timedelta(0)
    if payload != {
        "attempt_id": attempt_id,
        "topic_id": str(topic_id),
        "topic_title": f"{language} title",
        "status": "submitted",
        "submitted_language": language,
        "submitted_at": submitted_at,
        "result": {"correct_count": correct_count, "total_count": total_count, "percentage": percentage},
    }:
        pytest.fail("Submitted attempt did not match the public history schema", pytrace=False)


def test_attempt_lifecycle_and_history_after_new_login(learner, bilingual_topic):
    client, user = learner
    topic = bilingual_topic
    publish(topic)
    first = start(client, topic, "en")
    assert_pending(first, topic, "en")
    attempt_id = first["attempt_id"]
    assert data(client.get(ATTEMPTS_URL)) == []
    assert data(client.get(attempt_url(attempt_id), params={"language": "en"})) == first
    assert_pending(data(client.get(attempt_url(attempt_id))), topic, "ru")

    submitted = data(post(client, submit_url(attempt_id), {"language": "en", "answers": correct_answers(first)}))
    assert_submitted(submitted, attempt_id, topic.pk, "en", 2, 2, 100.0)
    assert data(client.get(attempt_url(attempt_id), params={"language": "ru"})) == submitted

    second = start(client, topic)
    second_id = second["attempt_id"]
    assert second_id != attempt_id
    second_result = data(post(client, submit_url(second_id), {"language": "ru", "answers": []}))
    assert_submitted(second_result, second_id, topic.pk, "ru", 0, 2, 0.0)
    assert Attempt.objects.filter(user=user, topic=topic).count() == 2
    assert data(client.get(ATTEMPTS_URL)) == [second_result, submitted]

    assert post(client, "/api/v1/auth/logout/", {}).status_code == 204
    assert_error(client.get(ATTEMPTS_URL), 403, "authentication_required")
    sign_in(client, user)
    assert data(client.get(ATTEMPTS_URL)) == [second_result, submitted]


def test_snapshot_keeps_both_languages_order_and_keys_after_edits_and_unpublish(learner, bilingual_topic):
    client, _ = learner
    topic = bilingual_topic
    publish(topic)
    ru = start(client, topic)
    attempt_id = ru["attempt_id"]
    en = data(client.get(attempt_url(attempt_id), params={"language": "en"}))
    assert_pending(ru, topic, "ru")
    assert_pending(en, topic, "en")
    stored = Attempt.objects.get(pk=attempt_id)
    original = stored.content_snapshot
    assert original["topic_id"] == str(topic.pk)
    assert original["topic_titles"] == {"ru": "ru title", "en": "en title"}
    earlier = start(client, topic)
    earlier_result = data(post(client, submit_url(earlier["attempt_id"]), {"language": "ru", "answers": []}))

    single = topic.questions.get(question_type=QuestionType.SINGLE_CHOICE)
    old_key = single.choices.get(position=10)
    new_key = single.choices.get(position=20)
    with edit_topics({topic.pk: topic.revision}, using="default"):
        topic.translations.update(title="Changed title")
        QuestionTranslation.objects.filter(question__topic=topic).update(text="Changed question")
        ChoiceTranslation.objects.filter(choice__question__topic=topic).update(text="Changed choice")
        single.position = 0
        single.save(update_fields=("position",))
        old_key.position = 40
        old_key.is_correct = False
        old_key.save(update_fields=("position", "is_correct"))
        new_key.is_correct = True
        new_key.save(update_fields=("is_correct",))
    assert data(client.get(attempt_url(attempt_id), params={"language": "en"})) == en

    topic.refresh_from_db()
    with edit_topics({topic.pk: topic.revision}, using="default") as topics:
        topics[topic.pk].status = TopicStatus.DRAFT
        old_key.delete()
    assert_error(post(client, start_url(topic.pk), {"language": "ru"}), 404, "not_found")
    assert data(client.get(attempt_url(attempt_id))) == ru
    assert data(client.get(ATTEMPTS_URL)) == [earlier_result]

    submitted = data(post(client, submit_url(attempt_id), {"language": "en", "answers": correct_answers(en)}))
    assert_submitted(submitted, attempt_id, topic.pk, "en", 2, 2, 100.0)
    assert data(client.get(ATTEMPTS_URL)) == [submitted, earlier_result]
    stored.refresh_from_db()
    if stored.content_snapshot != original:
        pytest.fail("The stored attempt snapshot changed", pytrace=False)
    assert Attempt.objects.filter(topic=topic).count() == 2


def test_submit_normalizes_order_and_omissions_and_rejects_valid_changes(learner, bilingual_topic):
    client, _ = learner
    publish(bilingual_topic)
    pending = start(client, bilingual_topic)
    attempt_id = pending["attempt_id"]
    url = submit_url(attempt_id)
    multiple, single = correct_answers(pending)
    first = data(post(client, url, {"language": "ru", "answers": [multiple]}))
    assert_submitted(first, attempt_id, bilingual_topic.pk, "ru", 1, 2, 50.0)
    row = Attempt.objects.get(pk=attempt_id)
    reordered = answer(multiple["question_id"], *reversed(multiple["choice_ids"]))
    retry = {"answers": [answer(single["question_id"]), reordered], "language": "ru"}
    assert data(post(client, url, retry)) == first

    assert_error(post(client, url, {**retry, "language": "en"}), 409, "attempt_already_submitted")
    assert_error(post(client, url, {**retry, "answers": [multiple, single]}), 409, "attempt_already_submitted")
    assert_error(
        post(client, url, {**retry, "answers": [answer(single["question_id"], "missing")]}),
        400, "validation_error",
    )
    after = Attempt.objects.get(pk=attempt_id)
    assert after.submitted_at == row.submitted_at
    assert after.submitted_answers == row.submitted_answers
    assert data(client.get(ATTEMPTS_URL)) == [first]
    assert Attempt.objects.count() == 1


@pytest.mark.parametrize("role", ["learner", "content_admin", "superuser"])
def test_attempt_access_is_scoped_to_the_owner_for_every_role(learner, bilingual_topic, role):
    client, _ = learner
    topic = bilingual_topic
    publish(topic)
    own = start(client, topic)
    unfinished = start(client, topic)
    own_result = data(post(client, submit_url(own["attempt_id"]), {"language": "ru", "answers": []}))

    if role == "superuser":
        other = User.objects.create_superuser("other-attempt@example.invalid", TEST_PASSWORD)
    else:
        other = User.objects.create_user("other-attempt@example.invalid", TEST_PASSWORD, is_staff=role == "content_admin")
        if role == "content_admin":
            other.groups.add(Group.objects.get(name="Content Admin"))

    with httpx.Client(base_url=client.base_url, trust_env=False) as outsider:
        sign_in(outsider, other)
        assert data(outsider.get(ATTEMPTS_URL)) == []
        missing = outsider.get(attempt_url("9223372036854775807"))
        assert_error(missing, 404, "not_found")
        for attempt in (own, unfinished):
            foreign = outsider.get(attempt_url(attempt["attempt_id"]))
            assert_error(foreign, 404, "not_found")
            assert foreign.json() == missing.json()
            assert_error(post(outsider, submit_url(attempt["attempt_id"]), {}), 404, "not_found")
        other_attempt = start(outsider, topic)
        other_result = data(post(outsider, submit_url(other_attempt["attempt_id"]), {"language": "ru", "answers": []}))
        assert data(outsider.get(ATTEMPTS_URL)) == [other_result]
    assert data(client.get(ATTEMPTS_URL)) == [own_result]
    assert Attempt.objects.get(pk=unfinished["attempt_id"]).status == AttemptStatus.IN_PROGRESS


def test_attempt_requests_require_authentication_csrf_and_valid_json(learner, bilingual_topic):
    client, user = learner
    topic = bilingual_topic
    publish(topic)
    url = start_url(topic.pk)
    with httpx.Client(base_url=client.base_url, trust_env=False) as anonymous:
        bootstrap(anonymous)
        for route in (ATTEMPTS_URL, attempt_url(1)):
            assert_error(anonymous.get(route), 403, "authentication_required")
        assert_error(post(anonymous, url, {"language": "ru"}), 403, "authentication_required")
        assert_error(post(anonymous, submit_url(1), {"language": "ru", "answers": []}), 403, "authentication_required")

    assert_error(client.post(url, json={"language": "ru"}), 403, "csrf_failed")
    response = client.post(url, data={"language": "ru"}, headers=csrf_header(client))
    assert_error(response, 415, "unsupported_media_type")
    response = client.post(url, content=b"{", headers={**csrf_header(client), "Content-Type": "application/json"})
    assert_error(response, 400, "validation_error")
    for body in ([], {}, {"language": "de"}, {"language": "en", "user_id": str(user.pk)}):
        assert_error(post(client, url, body), 400, "validation_error")
    response = client.get(url)
    assert_error(response, 405, "method_not_allowed")
    assert response.headers["Allow"] == "POST"
    for invalid_topic in ("invalid", topic.pk + 1_000_000, "9223372036854775808"):
        assert_error(post(client, start_url(invalid_topic), {"language": "en"}), 404, "not_found")
    assert not Attempt.objects.exists()


def test_invalid_submission_leaves_pending_attempt_unchanged(learner, bilingual_topic):
    client, _ = learner
    publish(bilingual_topic)
    pending = start(client, bilingual_topic)
    attempt_id = pending["attempt_id"]
    url = submit_url(attempt_id)
    multiple, single = correct_answers(pending)
    choices = multiple["choice_ids"]
    single_options = next(
        question["choices"] for question in pending["questions"] if question["question_id"] == single["question_id"]
    )
    for invalid_answers in (
        {},
        [answer("unknown-question")],
        [answer(multiple["question_id"], "unknown-choice")],
        [answer(single["question_id"], choices[0])],
        [answer(multiple["question_id"], choices[0], choices[0])],
        [multiple, multiple],
        [answer(single["question_id"], *(choice["choice_id"] for choice in single_options[:2]))],
        [answer(single["question_id"], int(single["choice_ids"][0]))],
    ):
        assert_error(post(client, url, {"language": "ru", "answers": invalid_answers}), 400, "validation_error")
    assert_error(post(client, url, {"language": "ru", "answers": [], "correct_count": 2}), 400, "validation_error")
    assert_error(post(client, url, {"answers": []}), 400, "validation_error")
    assert_error(client.post(url, json={"language": "ru", "answers": []}), 403, "csrf_failed")
    assert_error(client.get(attempt_url(attempt_id), params={"language": "de"}), 400, "validation_error")
    assert_error(post(client, submit_url("invalid"), {"language": "ru", "answers": []}), 404, "not_found")
    row = Attempt.objects.get(pk=attempt_id)
    assert row.status == AttemptStatus.IN_PROGRESS
    assert row.submitted_at is row.submitted_language is row.submitted_answers is row.correct_count is row.total_count is None
    assert data(client.get(attempt_url(attempt_id))) == pending
    assert data(client.get(ATTEMPTS_URL)) == []


@pytest.mark.parametrize("same_payload", [True, False], ids=["equivalent", "different"])
def test_concurrent_submissions_commit_one_result(learner, bilingual_topic, same_payload):
    client, user = learner
    topic = bilingual_topic
    publish(topic)
    pending = start(client, topic)
    attempt_id = pending["attempt_id"]
    url = submit_url(attempt_id)
    answers = correct_answers(pending)
    reordered = [answer(item["question_id"], *reversed(item["choice_ids"])) for item in reversed(answers)]

    with httpx.Client(base_url=client.base_url, trust_env=False) as second_client:
        sign_in(second_client, user)
        with ThreadPoolExecutor(max_workers=2) as pool:
            with transaction.atomic():
                Attempt.objects.select_for_update().get(pk=attempt_id)
                first = pool.submit(post, client, url, {"language": "ru", "answers": answers})
                wait_for_lock_waiters("assessments_attempt", 1)
                second = pool.submit(post, second_client, url, {
                    "language": "ru", "answers": reordered if same_payload else [],
                })
                wait_for_lock_waiters("assessments_attempt", 2)

            first_result = data(first.result(timeout=15))
            second_response = second.result(timeout=15)
            if same_payload:
                assert data(second_response) == first_result
            else:
                assert_error(second_response, 409, "attempt_already_submitted")

    assert_submitted(first_result, attempt_id, topic.pk, "ru", 2, 2, 100.0)
    assert data(client.get(ATTEMPTS_URL)) == [first_result]
    assert Attempt.objects.filter(user=user, topic=topic).count() == 1
    assert Attempt.objects.get(pk=attempt_id).submitted_at == datetime.fromisoformat(first_result["submitted_at"])


def test_start_waits_for_topic_transition_before_capturing_snapshot(learner, bilingual_topic):
    client, _ = learner
    publish(bilingual_topic)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            topic = Topic.objects.select_for_update().get(pk=bilingual_topic.pk)
            started = pool.submit(post, client, start_url(topic.pk), {"language": "ru"})
            wait_for_lock_waiters("learning_topic", 1)
            topic.status = TopicStatus.DRAFT
            topic.save(update_fields=("status",))
        assert_error(started.result(timeout=15), 404, "not_found")
    assert not Attempt.objects.exists()


def test_content_admin_cannot_delete_topic_with_attempts_or_open_attempt_admin(learner, bilingual_topic):
    client, _ = learner
    topic = bilingual_topic
    publish(topic)
    pending = start(client, topic)
    attempt_id = pending["attempt_id"]
    assert post(client, submit_url(attempt_id), {"language": "ru", "answers": []}).status_code == 200
    editor = content_editor("attempt-content-editor")
    assert not editor.has_perm("assessments.view_attempt")
    with httpx.Client(base_url=client.base_url, trust_env=False) as admin_client:
        sign_in_admin(admin_client, editor)
        for url in ("/admin/assessments/attempt/", f"/admin/assessments/attempt/{attempt_id}/change/"):
            assert admin_client.get(url).status_code == 404
        deletion = admin_url(Topic, "delete", topic)
        assert admin_client.get(deletion).status_code == 200
        response = admin_client.post(
            deletion, data={"post": "yes", "expected_revision": topic.revision}, headers=csrf_header(admin_client),
        )
        assert response.status_code == 200
        if "защищена от удаления" not in response.text or "Attempt object" in response.text:
            pytest.fail("Protected deletion did not preserve attempt privacy", pytrace=False)
    assert Topic.objects.filter(pk=topic.pk).exists()
    assert Attempt.objects.filter(pk=attempt_id, topic=topic).exists()
