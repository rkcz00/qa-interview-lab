from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from .models import Question, QuestionType


class InvalidAnswers(ValueError):
    """The submitted answer array violates the learner contract."""


@dataclass(frozen=True, slots=True)
class QuestionKey:
    question_id: str
    question_type: str
    choice_ids: frozenset[str]
    correct_choice_ids: frozenset[str] = field(repr=False)

    def __post_init__(self):
        key_size = len(self.correct_choice_ids)
        valid_key_size = (
            (self.question_type == QuestionType.SINGLE_CHOICE and key_size == 1)
            or (self.question_type == QuestionType.MULTIPLE_CHOICE and key_size >= 2)
        )
        if (
            not isinstance(self.question_id, str)
            or not self.question_id
            or len(self.choice_ids) < 2
            or not self.correct_choice_ids <= self.choice_ids
            or not valid_key_size
        ):
            raise ValueError("Invalid server-side question key.")

    @classmethod
    def from_question(cls, question: Question):
        if question.pk is None or question._state.adding:
            raise ValueError("A saved question is required.")
        choices = list(question.choices.all())
        return cls(
            question_id=str(question.pk),
            question_type=question.question_type,
            choice_ids=frozenset(str(choice.pk) for choice in choices),
            correct_choice_ids=frozenset(str(choice.pk) for choice in choices if choice.is_correct),
        )


def score_answers(questions: Iterable[QuestionKey], answers: object) -> dict[str, int | float]:
    """Evaluate a learner answer array against server-side question keys."""
    by_id = {}
    for question in questions:
        if question.question_id in by_id:
            raise ValueError("Question keys must be unique.")
        by_id[question.question_id] = question
    total_count = len(by_id)
    if total_count == 0:
        raise ValueError("At least one question is required.")
    if not isinstance(answers, list):
        raise InvalidAnswers("Answers must be an array.")

    answered = set()
    correct_count = 0
    for answer in answers:
        if not isinstance(answer, dict) or answer.keys() != {"question_id", "choice_ids"}:
            raise InvalidAnswers("Each answer must contain question_id and choice_ids.")
        question_id = answer["question_id"]
        choice_ids = answer["choice_ids"]
        if not isinstance(question_id, str) or not isinstance(choice_ids, list):
            raise InvalidAnswers("Expected a string question ID and an array of choice IDs.")
        if any(not isinstance(choice_id, str) for choice_id in choice_ids):
            raise InvalidAnswers("Choice IDs must be strings.")
        if question_id in answered or question_id not in by_id:
            raise InvalidAnswers("Unknown or duplicate question ID.")

        selected = set(choice_ids)
        question = by_id[question_id]
        if len(selected) != len(choice_ids) or not selected <= question.choice_ids:
            raise InvalidAnswers("Invalid or duplicate choice ID for this question.")
        if question.question_type == QuestionType.SINGLE_CHOICE and len(selected) > 1:
            raise InvalidAnswers("Single-choice accepts at most one choice.")
        answered.add(question_id)
        if selected == question.correct_choice_ids:
            correct_count += 1

    # Round the exact ratio in hundredths of a percent using ROUND_HALF_UP.
    hundredths, remainder = divmod(10_000 * correct_count, total_count)
    if 2 * remainder >= total_count:
        hundredths += 1
    return {"correct_count": correct_count, "total_count": total_count, "percentage": hundredths / 100}


def is_mastered(*, article_read_at: datetime | None, submitted_counts: Iterable[tuple[int, int]]) -> bool:
    """Combine the read mark with the counts of individual submitted attempts."""
    if article_read_at is None:
        return False
    for correct_count, total_count in submitted_counts:
        if type(correct_count) is not int or type(total_count) is not int:
            raise ValueError("Result counts must be integers.")
        if total_count <= 0 or not 0 <= correct_count <= total_count:
            raise ValueError("Invalid result counts.")
        if 100 * correct_count >= 80 * total_count:
            return True
    return False
