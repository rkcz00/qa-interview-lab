"""Read-only completion projection, independent of the historical mastery rule."""

from fractions import Fraction

from django.contrib.auth import get_user_model
from django.contrib.postgres.expressions import ArraySubquery
from django.db.models import Case, CharField, Exists, OuterRef, PositiveBigIntegerField, Subquery, Value, When
from django.db.models.functions import Cast, Coalesce, JSONObject
from django.utils.dateparse import parse_datetime

from apps.learning.models import Topic, TopicStatus
from apps.practice.models import PracticeKind, PracticeSubmission, PracticeTask, SubmissionStatus

from .models import Attempt, AttemptStatus, Question, TopicProgress, UserProgressState
from .progress import summarize_progress


ACTIVITY_STATUSES = frozenset(("unattempted", "failed", "passed"))


def completion_value(read, statuses):
    """Return an exact percentage before display rounding, including M=0."""
    statuses = tuple(statuses)
    if type(read) is not bool or any(status not in ACTIVITY_STATUSES for status in statuses):
        raise ValueError("Invalid completion input")
    return Fraction(30 * read) + (Fraction(70 * statuses.count("passed"), len(statuses)) if statuses else 0)


def rounded_percentage(value):
    # Exact ROUND_HALF_UP on a nonnegative rational; no rounded topic average.
    cents, remainder = divmod(value.numerator * 100, value.denominator)
    return (cents + int(2 * remainder >= value.denominator)) / 100


def _completion_snapshot(user_id):
    """One PostgreSQL statement also covers the empty catalog and concurrent reset."""
    counts = Attempt.objects.filter(
        user_id=user_id, topic_id=OuterRef("pk"), status=AttemptStatus.SUBMITTED,
    ).order_by("pk").values(value=JSONObject(correct_count="correct_count", total_count="total_count"))
    marks = TopicProgress.objects.filter(user_id=user_id, topic_id=OuterRef("pk"))
    submissions = PracticeSubmission.objects.filter(user_id=user_id, task_id=OuterRef("pk"), status=SubmissionStatus.SUBMITTED)
    tasks = PracticeTask.objects.filter(
        topic_practice__topic_id=OuterRef("pk"), status=TopicStatus.PUBLISHED,
        topic_practice__practice_kind=PracticeKind.SINGLE_CORRECT_ANSWER,
    ).annotate(activity_status=Case(
        When(Exists(submissions.filter(verdict="correct")), then=Value("passed")),
        When(Exists(submissions), then=Value("failed")),
        default=Value("unattempted"), output_field=CharField(),
    )).values(value=JSONObject(task_id=Cast("pk", CharField()), status="activity_status"))
    topics = Topic.objects.filter(status=TopicStatus.PUBLISHED).order_by("pk").annotate(
        read_at=Subquery(marks.values("article_read_at")[:1]),
        counts=ArraySubquery(counts),
        completion_practice=Subquery(tasks[:1]),
        has_test=Exists(Question.objects.filter(topic_id=OuterRef("pk"))),
    ).values(value=JSONObject(
        topic_id=Cast("pk", CharField()), article_read_at="read_at", counts="counts",
        practice="completion_practice", has_test="has_test",
    ))
    state = UserProgressState.objects.filter(user_id=OuterRef("pk"))
    return get_user_model().objects.filter(pk=user_id).annotate(
        progress_generation=Coalesce(Subquery(state.values("generation")[:1]), Value(1), output_field=PositiveBigIntegerField()),
        topic_values=ArraySubquery(topics),
    ).values("progress_generation", "topic_values").get()


def completion_progress(user_id):
    snapshot = _completion_snapshot(user_id)
    topics = []
    exact_values = []
    for item in snapshot["topic_values"]:
        at = parse_datetime(item["article_read_at"]) if item["article_read_at"] else None
        legacy = summarize_progress(item["topic_id"], at, (
            (row["correct_count"], row["total_count"]) for row in item["counts"]
        ))
        best = legacy["best_result"]
        test_status = "unattempted" if best is None else (
            "passed" if best["correct_count"] * 100 >= best["total_count"] * 80 else "failed"
        )
        statuses = [test_status] if item["has_test"] else []
        if item["practice"] is not None:
            statuses.append(item["practice"]["status"])
        value = completion_value(at is not None, statuses)
        exact_values.append(value)
        topics.append({
            "topic_id": item["topic_id"], "article_read_at": at,
            "test": {"status": test_status, "best_result": best}, "practice": item["practice"],
            "completion_progress": rounded_percentage(value), "mastered": legacy["mastered"],
        })
    average = sum(exact_values, Fraction()) / len(exact_values) if exact_values else Fraction()
    return {
        "progress_generation": str(snapshot["progress_generation"]),
        "overall_completion_progress": rounded_percentage(average), "topics": topics,
    }
