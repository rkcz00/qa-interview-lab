from copy import deepcopy

import pytest

from apps.assessments.attempts import IncompleteAnswers, grade_initial_snapshot, grade_snapshot
from apps.assessments.scoring import InvalidAnswers


SNAPSHOT = {"questions": [
    {"question_id": "1", "question_type": "single_choice", "choices": [
        {"choice_id": "11", "is_correct": True}, {"choice_id": "12", "is_correct": False},
    ]},
    {"question_id": "2", "question_type": "multiple_choice", "choices": [
        {"choice_id": "21", "is_correct": True}, {"choice_id": "22", "is_correct": True},
        {"choice_id": "23", "is_correct": False},
    ]},
]}
COMPLETE = [{"question_id": "1", "choice_ids": ["11"]}, {"question_id": "2", "choice_ids": ["21", "22"]}]


@pytest.mark.parametrize("answers", [[], COMPLETE[:1], [{"question_id": "1"}],
    [{"question_id": "1", "choice_ids": []}, COMPLETE[1]],
    [COMPLETE[0], {"question_id": "2", "choice_ids": []}]])
def test_first_submit_requires_every_question_and_nonempty_selection(answers):
    before = deepcopy((SNAPSHOT, answers))
    with pytest.raises(IncompleteAnswers):
        grade_initial_snapshot(SNAPSHOT, answers)
    assert (SNAPSHOT, answers) == before


@pytest.mark.parametrize("invalid", [None, {}, [None], [{"choice_ids": []}],
    [{"question_id": "missing"}], [{"question_id": 1}],
    [{"question_id": "1", "choice_ids": ["missing"]}],
    [{"question_id": "1", "choice_ids": ["11", "12"]}],
    [{"question_id": "1", "choice_ids": ["11", "11"]}],
    [{"question_id": "1"}, {"question_id": "1"}],
    [{"question_id": "1", "choice_ids": [], "confirmed": True}],
])
def test_structural_validation_has_priority_over_incompleteness(invalid):
    with pytest.raises(InvalidAnswers):
        grade_initial_snapshot(SNAPSHOT, invalid)


def test_complete_payload_preserves_exact_set_scoring_and_normalization():
    for answers, expected in ((COMPLETE, 2),
        ([COMPLETE[0], {"question_id": "2", "choice_ids": ["21"]}], 1),
        ([{"question_id": "1", "choice_ids": ["12"]}, {"question_id": "2", "choice_ids": ["23"]}], 0)):
        assert grade_initial_snapshot(SNAPSHOT, answers) == grade_snapshot(SNAPSHOT, answers)
        assert grade_initial_snapshot(SNAPSHOT, answers)[1] == {
            "correct_count": expected, "total_count": 2, "percentage": expected * 50,
        }


def test_historical_scoring_keeps_omitted_answers_and_zero_counts():
    normalized, result = grade_snapshot(SNAPSHOT, [])
    assert normalized == [{"question_id": "1", "choice_ids": []}, {"question_id": "2", "choice_ids": []}]
    assert result == {"correct_count": 0, "total_count": 2, "percentage": 0}
