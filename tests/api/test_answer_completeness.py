from copy import deepcopy

import pytest

from apps.assessments.models import Attempt
from apps.learning.tests.test_content import bilingual_topic

from .test_attempts import (
    learner, start, post, data, answer, correct_answers, submit_url, ATTEMPTS_URL,
)
from .test_registration import assert_error


@pytest.mark.parametrize("missing", ["answers", "empty", "question", "choice_ids", "empty_choice"])
def test_incomplete_first_submit_is_400_without_any_saved_result(learner, bilingual_topic, missing):
    client, _ = learner
    from .test_catalog import publish
    publish(bilingual_topic)
    pending = start(client, bilingual_topic)
    answers = correct_answers(pending)
    payload = {"language": "ru", "answers": deepcopy(answers)}
    if missing == "answers":
        payload.pop("answers")
    elif missing == "empty":
        payload["answers"] = []
    elif missing == "question":
        payload["answers"] = answers[:1]
    elif missing == "choice_ids":
        payload["answers"][0].pop("choice_ids")
    else:
        payload["answers"][0]["choice_ids"] = []
    before = Attempt.objects.get(pk=pending["attempt_id"])
    response = post(client, submit_url(pending["attempt_id"]), payload)
    assert response.status_code == 400
    assert response.json() == {"error": {"code": "incomplete_answers", "message": "Answer every question before submitting the test."}}
    after = Attempt.objects.get(pk=before.pk)
    assert after.status == "in_progress"
    assert after.submitted_at is after.submitted_answers is after.correct_count is after.total_count is None
    assert after.content_snapshot == before.content_snapshot
    assert data(client.get(ATTEMPTS_URL)) == []
    result = data(post(client, submit_url(pending["attempt_id"]), {"language": "ru", "answers": answers}))
    assert result["result"] == {"correct_count": 2, "total_count": 2, "percentage": 100}


@pytest.mark.parametrize("invalid", ["language", "extra", "unknown_question", "unknown_choice", "duplicate", "multiple_single", "type", "missing_question_id"])
def test_invalid_structure_precedes_incomplete_answers(learner, bilingual_topic, invalid):
    client, _ = learner
    from .test_catalog import publish
    publish(bilingual_topic)
    pending = start(client, bilingual_topic)
    multiple, single = correct_answers(pending)
    payload = {"language": "ru", "answers": [{"question_id": multiple["question_id"]}]}
    if invalid == "language":
        payload["language"] = "de"
    elif invalid == "extra":
        payload["confirmed"] = True
    elif invalid == "unknown_question":
        payload["answers"].append(answer("missing"))
    elif invalid == "unknown_choice":
        payload["answers"].append(answer(single["question_id"], "missing"))
    elif invalid == "duplicate":
        payload["answers"].append(answer(multiple["question_id"]))
    elif invalid == "multiple_single":
        question = next(q for q in pending["questions"] if q["question_id"] == single["question_id"])
        payload["answers"].append(answer(single["question_id"], *(c["choice_id"] for c in question["choices"][:2])))
    elif invalid == "type":
        payload["answers"] = None
    else:
        payload["answers"].append({"choice_ids": []})
    assert_error(post(client, submit_url(pending["attempt_id"]), payload), 400, "validation_error")
    assert Attempt.objects.get(pk=pending["attempt_id"]).status == "in_progress"
