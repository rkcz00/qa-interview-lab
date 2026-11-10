from datetime import UTC, datetime

import pytest

from apps.assessments.models import QuestionType
from apps.assessments.scoring import InvalidAnswers, QuestionKey, is_mastered, score_answers
from apps.learning.models import Language
from apps.learning.tests.test_content import bilingual_topic


SINGLE = QuestionKey("q1", QuestionType.SINGLE_CHOICE, frozenset({"a", "b"}), frozenset({"a"}))
MULTIPLE = QuestionKey("q2", QuestionType.MULTIPLE_CHOICE, frozenset({"c", "d", "e"}), frozenset({"c", "e"}))
READ_AT = datetime(2026, 1, 1, tzinfo=UTC)


def answer(question_id, *choices):
    return {"question_id": question_id, "choice_ids": list(choices)}


@pytest.mark.parametrize(
    ("question", "choices", "correct_count", "percentage"),
    [
        (SINGLE, ("a",), 1, 100.0),
        (SINGLE, ("b",), 0, 0.0),
        (SINGLE, (), 0, 0.0),
        (MULTIPLE, ("c", "e"), 1, 100.0),
        (MULTIPLE, ("e", "c"), 1, 100.0),
        (MULTIPLE, ("c",), 0, 0.0),
        (MULTIPLE, ("c", "d", "e"), 0, 0.0),
        (MULTIPLE, ("d",), 0, 0.0),
        (MULTIPLE, (), 0, 0.0),
    ],
)
def test_choice_sets_match_exactly(question, choices, correct_count, percentage):
    result = score_answers([question], [answer(question.question_id, *choices)])
    assert result == {"correct_count": correct_count, "total_count": 1, "percentage": percentage}


@pytest.mark.parametrize(
    ("answers", "correct_count", "percentage"),
    [
        ([answer("q2", "e", "c"), answer("q1", "a")], 2, 100.0),
        ([answer("q1", "b"), answer("q2", "d")], 0, 0.0),
        ([answer("q1", "a"), answer("q2", "c")], 1, 50.0),
        ([answer("q1", "a")], 1, 50.0),
        ([], 0, 0.0),
    ],
)
def test_result_only_contains_aggregates_and_counts_skipped_questions(answers, correct_count, percentage):
    assert score_answers([SINGLE, MULTIPLE], answers) == {
        "correct_count": correct_count, "total_count": 2, "percentage": percentage,
    }


@pytest.mark.parametrize(
    ("correct_count", "total_count", "percentage"),
    [(1, 32, 3.13), (1, 3, 33.33), (2, 3, 66.67)],
)
def test_percentage_rounds_exact_ratio_half_up(correct_count, total_count, percentage):
    questions = [
        QuestionKey(str(i), QuestionType.SINGLE_CHOICE, frozenset({f"{i}-a", f"{i}-b"}), frozenset({f"{i}-a"}))
        for i in range(total_count)
    ]
    answers = [answer(str(i), f"{i}-a") for i in range(correct_count)]
    assert score_answers(questions, answers) == {
        "correct_count": correct_count, "total_count": total_count, "percentage": percentage,
    }


@pytest.mark.parametrize(
    "answers",
    [
        pytest.param(None, id="null-answers"),
        pytest.param({}, id="object-instead-of-array"),
        pytest.param([None], id="null-answer"),
        pytest.param([{"question_id": "q1"}], id="missing-choice-ids"),
        pytest.param([{"choice_ids": ["a"]}], id="missing-question-id"),
        pytest.param([{**answer("q1", "a"), "correct_count": 1}], id="client-score"),
        pytest.param([answer(1, "a")], id="numeric-question-id"),
        pytest.param([{"question_id": "q1", "choice_ids": "a"}], id="choices-not-array"),
        pytest.param([answer("q1", 1)], id="numeric-choice-id"),
        pytest.param([answer("q1", True)], id="boolean-choice-id"),
        pytest.param([answer("missing", "a")], id="unknown-question"),
        pytest.param([answer("q1", "a"), answer("q1", "a")], id="duplicate-question"),
        pytest.param([answer("q2", "c", "e", "missing")], id="unknown-choice"),
        pytest.param([answer("q2", "c", "e", "a")], id="foreign-choice"),
        pytest.param([answer("q2", "c", "c", "e")], id="duplicate-choice"),
        pytest.param([answer("q1", "a", "b")], id="several-single-choices"),
    ],
)
def test_invalid_answers_are_rejected(answers):
    with pytest.raises(InvalidAnswers):
        score_answers([SINGLE, MULTIPLE], answers)


def test_empty_test_and_duplicate_server_questions_are_rejected():
    with pytest.raises(ValueError, match="At least one question"):
        score_answers([], [])
    with pytest.raises(ValueError, match="unique"):
        score_answers([SINGLE, SINGLE], [])


def test_invalid_server_key_cannot_award_points_for_a_blank_answer():
    with pytest.raises(ValueError, match="Invalid server-side question key"):
        QuestionKey("q1", QuestionType.SINGLE_CHOICE, frozenset({"a", "b"}), frozenset())


@pytest.mark.parametrize(
    ("article_read_at", "submitted_counts", "expected"),
    [
        (None, [(81, 100)], False),
        (READ_AT, [], False),
        (READ_AT, [(79, 100)], False),
        (READ_AT, [(80, 100)], True),
        (READ_AT, [(81, 100)], True),
        (READ_AT, [(4, 5)], True),
        (READ_AT, [(3, 5)], False),
        (READ_AT, [(199, 250)], False),
        (READ_AT, [(39_999, 50_000)], False),  # 79.998% displays as 80.00%.
        (READ_AT, [(3, 5), (1, 2)], False),
        (READ_AT, [(4, 5), (1, 5)], True),
    ],
)
def test_mastery_uses_read_mark_and_exact_counts_from_one_submission(article_read_at, submitted_counts, expected):
    assert is_mastered(article_read_at=article_read_at, submitted_counts=submitted_counts) is expected


@pytest.mark.parametrize("counts", [(0, 0), (-1, 5), (6, 5), (True, 1)])
def test_mastery_rejects_invalid_submitted_counts(counts):
    with pytest.raises(ValueError):
        is_mastered(article_read_at=READ_AT, submitted_counts=[counts])


@pytest.mark.parametrize("article_language,test_language", [(Language.RU, Language.EN), (Language.EN, Language.RU)])
def test_scores_postgres_choices_independently_of_translations(
    bilingual_topic, django_assert_num_queries, article_language, test_language,
):
    article = bilingual_topic.translations.get(language=article_language)
    assert article.language == article_language
    questions = list(bilingual_topic.questions.prefetch_related("choices"))
    answers = []
    for question in questions:
        localized_question = question.translations.get(language=test_language)
        correct_positions = (10,) if question.question_type == QuestionType.SINGLE_CHOICE else (20, 10)
        localized_choices = [
            question.choices.get(position=position).translations.get(language=test_language)
            for position in correct_positions
        ]
        answers.append(answer(str(localized_question.question_id), *(str(choice.choice_id) for choice in localized_choices)))

    with django_assert_num_queries(0):
        keys = [QuestionKey.from_question(question) for question in questions]
        assert score_answers(keys, answers) == {"correct_count": 2, "total_count": 2, "percentage": 100.0}
        assert score_answers(keys, answers[:1]) == {"correct_count": 1, "total_count": 2, "percentage": 50.0}


def test_rejects_an_existing_postgres_choice_from_a_different_question(bilingual_topic):
    single = bilingual_topic.questions.get(question_type=QuestionType.SINGLE_CHOICE)
    multiple = bilingual_topic.questions.get(question_type=QuestionType.MULTIPLE_CHOICE)
    foreign_choice = multiple.choices.get(position=10)
    keys = [QuestionKey.from_question(single), QuestionKey.from_question(multiple)]
    with pytest.raises(InvalidAnswers):
        score_answers(keys, [answer(str(single.pk), str(foreign_choice.pk))])
