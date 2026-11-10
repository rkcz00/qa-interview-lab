from apps.learning.models import require_translations

from .scoring import QuestionKey, grade_answers


def _texts_by_language(translations, field):
    rows = list(translations)
    require_translations(rows, fields=(field,), label="Attempt snapshot")
    return {row.language: getattr(row, field) for row in rows}


def build_snapshot(topic):
    """Capture the score keys and both languages while the topic row is locked."""
    questions = []
    for question in topic.questions.all():
        key = QuestionKey.from_question(question)
        questions.append({
            "question_id": key.question_id,
            "question_type": key.question_type,
            "position": question.position,
            "texts": _texts_by_language(question.translations.all(), "text"),
            "choices": [
                {
                    "choice_id": str(choice.pk),
                    "position": choice.position,
                    "texts": _texts_by_language(choice.translations.all(), "text"),
                    "is_correct": str(choice.pk) in key.correct_choice_ids,
                }
                for choice in question.choices.all()
            ],
        })
    if not questions:
        raise ValueError("An attempt requires at least one question.")

    return {
        "topic_id": str(topic.pk),
        "topic_titles": _texts_by_language(topic.translations.all(), "title"),
        "questions": questions,
    }


def grade_snapshot(snapshot, answers):
    questions = (
        QuestionKey(
            question_id=question["question_id"],
            question_type=question["question_type"],
            choice_ids=frozenset(choice["choice_id"] for choice in question["choices"]),
            correct_choice_ids=frozenset(
                choice["choice_id"] for choice in question["choices"] if choice["is_correct"]
            ),
        )
        for question in snapshot["questions"]
    )
    return grade_answers(questions, answers)
