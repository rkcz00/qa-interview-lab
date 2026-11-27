"""Read-only completion projection, independent of the historical mastery rule."""

from fractions import Fraction

from django.contrib.auth import get_user_model
from django.contrib.postgres.expressions import ArraySubquery
from django.db.models import Case, CharField, Exists, OuterRef, PositiveBigIntegerField, Subquery, Value, When
from django.db.models.functions import Cast, Coalesce, JSONObject
from django.utils.dateparse import parse_datetime

from apps.learning.models import Topic, TopicStatus
from apps.practice.models import PracticeKind, PracticeSubmission, PracticeTask, SubmissionStatus

from .models import Attempt, AttemptStatus, Question, UserProgressState
from .progress import summarize_progress
from .reading import aggregate_read_at, article_contribution, rounded_percentage, with_reading


ACTIVITY_STATUSES = frozenset(("unattempted", "failed", "passed"))


def completion_value(read, statuses, *, total_sections=1, read_sections=None):
    """Return an exact percentage before display rounding, including M=0."""
    statuses = tuple(statuses)
    if type(read) is not bool or any(status not in ACTIVITY_STATUSES for status in statuses):
        raise ValueError("Invalid completion input")
    read_sections = int(read) if read_sections is None else read_sections
    contribution = article_contribution(total_sections, read_sections)
    if read is not (total_sections > 0 and read_sections == total_sections):
        raise ValueError("Inconsistent aggregate Read")
    return contribution + (Fraction(70 * statuses.count("passed"), len(statuses)) if statuses else 0)


def _completion_snapshot(user_id):
    """One PostgreSQL statement also covers the empty catalog and concurrent reset."""
    counts = Attempt.objects.filter(
        user_id=user_id, topic_id=OuterRef("pk"), status=AttemptStatus.SUBMITTED,
    ).order_by("pk").values(value=JSONObject(correct_count="correct_count", total_count="total_count"))
    submissions = PracticeSubmission.objects.filter(user_id=user_id, task_id=OuterRef("pk"), status=SubmissionStatus.SUBMITTED)
    tasks = PracticeTask.objects.filter(
        topic_practice__topic_id=OuterRef("pk"), status=TopicStatus.PUBLISHED,
        topic_practice__practice_kind=PracticeKind.SINGLE_CORRECT_ANSWER,
    ).annotate(activity_status=Case(
        When(Exists(submissions.filter(verdict="correct")), then=Value("passed")),
        When(Exists(submissions), then=Value("failed")),
        default=Value("unattempted"), output_field=CharField(),
    )).values(value=JSONObject(task_id=Cast("pk", CharField()), status="activity_status"))
    topics = with_reading(Topic.objects.filter(status=TopicStatus.PUBLISHED), user_id).order_by("pk").annotate(
        counts=ArraySubquery(counts),
        completion_practice=Subquery(tasks[:1]),
        has_test=Exists(Question.objects.filter(topic_id=OuterRef("pk"))),
    ).values(value=JSONObject(
        topic_id=Cast("pk", CharField()), legacy_read_at="legacy_read_at", latest_read_at="latest_section_read_at",
        sections_total="sections_total", sections_read="sections_read", counts="counts",
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
        if not item["sections_total"]:
            raise RuntimeError("Published topic has no sections")
        at = aggregate_read_at(
            item["sections_total"], item["sections_read"],
            parse_datetime(item["legacy_read_at"]) if item["legacy_read_at"] else None,
            parse_datetime(item["latest_read_at"]) if item["latest_read_at"] else None,
        )
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
        value = completion_value(at is not None, statuses, total_sections=item["sections_total"], read_sections=item["sections_read"])
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
