from django.contrib.postgres.expressions import ArraySubquery
from django.db.models import Exists, OuterRef
from django.db.models.functions import JSONObject

from apps.learning.models import Topic

from .models import Attempt, AttemptStatus, TopicProgress, TopicSectionProgress
from .reading import aggregate_read_at, with_reading
from .scoring import is_mastered, result_from_counts


def summarize_progress(topic_id, article_read_at, submitted_counts):
    """Project completed, immutable results without caching scores or mastery."""
    best_counts = None
    best_result = None
    for correct_count, total_count in submitted_counts:
        result = result_from_counts(correct_count, total_count)
        if best_counts is None or correct_count * best_counts[1] > best_counts[0] * total_count:
            best_counts = (correct_count, total_count)
            best_result = result
    return {
        "topic_id": str(topic_id),
        "article_read_at": article_read_at,
        "best_result": best_result,
        "mastered": is_mastered(
            article_read_at=article_read_at, submitted_counts=() if best_counts is None else (best_counts,),
        ),
    }


def _submitted_attempts(user_id):
    # Fetch aggregate counts only: progress never needs the snapshot or answers.
    # Exact ties keep the earlier stored attempt, independent of query planning.
    return Attempt.objects.filter(user_id=user_id, status=AttemptStatus.SUBMITTED).order_by("pk")


def progress_after_read(mark):
    return next(row for row in user_progress(mark.user_id) if row["topic_id"] == str(mark.topic_id))


def user_progress(user_id):
    """One coherent projection, including partial reading and historical Draft topics."""
    submitted = _submitted_attempts(user_id).filter(topic_id=OuterRef("pk"))
    legacy = TopicProgress.objects.filter(user_id=user_id, topic_id=OuterRef("pk"))
    marks = TopicSectionProgress.objects.filter(user_id=user_id, section__topic_id=OuterRef("pk"))
    rows = with_reading(Topic.objects.filter(Exists(submitted) | Exists(legacy) | Exists(marks)), user_id).annotate(
        counts=ArraySubquery(submitted.values(item=JSONObject(correct_count="correct_count", total_count="total_count"))),
    ).order_by("pk").values("pk", "sections_total", "sections_read", "legacy_read_at", "latest_section_read_at", "counts")
    return [
        summarize_progress(
            row["pk"], aggregate_read_at(row["sections_total"], row["sections_read"], row["legacy_read_at"], row["latest_section_read_at"]),
            ((item["correct_count"], item["total_count"]) for item in row["counts"]),
        ) for row in rows
    ]
