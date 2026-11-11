from collections import defaultdict

from .models import Attempt, AttemptStatus, TopicProgress
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
    counts = _submitted_attempts(mark.user_id).filter(topic_id=mark.topic_id).values_list("correct_count", "total_count")
    return summarize_progress(mark.topic_id, mark.article_read_at, counts)


def user_progress(user_id):
    """List the owner's read marks and completed attempts, including Draft topics."""
    read_marks = dict(TopicProgress.objects.filter(user_id=user_id).values_list("topic_id", "article_read_at"))
    counts = defaultdict(list)
    for topic_id, correct_count, total_count in _submitted_attempts(user_id).values_list(
        "topic_id", "correct_count", "total_count",
    ):
        counts[topic_id].append((correct_count, total_count))
    return [
        summarize_progress(topic_id, read_marks.get(topic_id), counts[topic_id])
        for topic_id in sorted(read_marks.keys() | counts.keys())
    ]
