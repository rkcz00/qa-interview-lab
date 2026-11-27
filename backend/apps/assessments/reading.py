"""Owner-scoped section reading; no cached completion or mastery flags."""

from fractions import Fraction

from django.contrib.postgres.expressions import ArraySubquery
from django.db.models import CharField, Count, OuterRef, PositiveBigIntegerField, Subquery, Value
from django.db.models.functions import Cast, Coalesce, JSONObject
from django.http import Http404
from django.utils.dateparse import parse_datetime

from apps.learning.models import Language, Topic, TopicSection, TopicSectionTranslation, TopicStatus, TopicTranslation

from .models import TopicProgress, TopicSectionProgress, UserProgressState


class SectionReadRequired(Exception):
    code = "section_read_required"
    message = "Use the section reader to read all published sections."


def rounded_percentage(value):
    cents, remainder = divmod(value.numerator * 100, value.denominator)
    return (cents + int(2 * remainder >= value.denominator)) / 100


def article_contribution(total, read):
    if type(total) is not int or type(read) is not int or not 0 <= read <= total:
        raise ValueError("Invalid section counts")
    return Fraction(30 * read, total) if total else Fraction()


def reading_state(total, read):
    return {
        "total_sections": total, "read_sections": read, "is_read": total > 0 and read == total,
        "completion_contribution": rounded_percentage(article_contribution(total, read)),
    }


def with_reading(queryset, user_id):
    """Correlated subqueries avoid multiplying marks by questions or attempts."""
    sections = TopicSection.objects.filter(topic_id=OuterRef("pk"), status=TopicStatus.PUBLISHED).order_by()
    marks = TopicSectionProgress.objects.filter(
        user_id=user_id, section__topic_id=OuterRef("pk"), section__status=TopicStatus.PUBLISHED,
    )
    counts = marks.order_by().values("section__topic_id").annotate(total=Count("pk")).values("total")
    return queryset.annotate(
        sections_total=Coalesce(Subquery(sections.values("topic_id").annotate(total=Count("pk")).values("total")), Value(0)),
        sections_read=Coalesce(Subquery(counts), Value(0)),
        latest_section_read_at=Subquery(marks.order_by("-read_at", "-pk").values("read_at")[:1]),
        legacy_read_at=Subquery(TopicProgress.objects.filter(user_id=user_id, topic_id=OuterRef("pk")).values("article_read_at")[:1]),
    )


def aggregate_read_at(total, read, legacy_at, latest_at):
    return (legacy_at or latest_at) if total > 0 and total == read else None


def topic_reading(user_id, topic_id):
    row = with_reading(Topic.objects.filter(pk=topic_id), user_id).values(
        "sections_total", "sections_read", "legacy_read_at", "latest_section_read_at",
    ).get()
    return row


def require_topic_read(user_id, topic_id):
    row = topic_reading(user_id, topic_id)
    if not row["sections_total"]:
        raise RuntimeError("Published topic has no sections")
    if row["sections_read"] != row["sections_total"]:
        raise SectionReadRequired()


def save_section_read(user_id, section):
    """The caller holds the existing User -> Topic transaction and generation check."""
    mark, _ = TopicSectionProgress.objects.get_or_create(user_id=user_id, section=section)
    state = topic_reading(user_id, section.topic_id)
    at = aggregate_read_at(state["sections_total"], state["sections_read"], state["legacy_read_at"], state["latest_section_read_at"])
    if at is not None:
        # Preserve the first legacy date for existing clients; never use this row as a gate.
        TopicProgress.objects.get_or_create(user_id=user_id, topic_id=section.topic_id, defaults={"article_read_at": at})
    return mark


def reading_snapshot(user_id, topic_id):
    """One PostgreSQL statement binds content, private read marks and reset generation."""
    texts = TopicSectionTranslation.objects.filter(section_id=OuterRef("pk")).order_by("language").values(
        item=JSONObject(language="language", title="title", article_body="article_body"),
    )
    marks = TopicSectionProgress.objects.filter(user_id=user_id, section_id=OuterRef("pk"))
    sections = TopicSection.objects.filter(topic_id=OuterRef("pk"), status=TopicStatus.PUBLISHED).order_by("position", "pk").annotate(
        read_at=Subquery(marks.values("read_at")[:1]), texts=ArraySubquery(texts),
    ).values(item=JSONObject(section_id=Cast("pk", CharField()), position="position", read_at="read_at", texts="texts"))
    titles = TopicTranslation.objects.filter(topic_id=OuterRef("pk")).order_by("language").values(
        item=JSONObject(language="language", title="title"),
    )
    rows = Topic.objects.filter(pk=topic_id, status=TopicStatus.PUBLISHED).annotate(
        titles=ArraySubquery(titles), section_values=ArraySubquery(sections),
        progress_generation=Coalesce(
            Subquery(UserProgressState.objects.filter(user_id=user_id).values("generation")[:1]),
            Value(1), output_field=PositiveBigIntegerField(),
        ),
    ).values("pk", "titles", "section_values", "progress_generation")
    snapshot = rows.first()
    if snapshot is None:
        raise Http404
    return snapshot


def _texts(rows, fields):
    texts = {row["language"]: row for row in rows}
    if set(texts) != set(Language.values) or any(
        not isinstance(row.get(field), str) or not row[field].strip()
        for row in texts.values() for field in fields
    ):
        raise RuntimeError("Published reading content is incomplete")
    return texts


def public_reading(snapshot, language, section_id=None):
    titles = _texts(snapshot["titles"], ("title",))
    sections = snapshot["section_values"]
    if not sections:
        raise RuntimeError("Published topic has no sections")
    public = []
    for section in sections:
        translation = _texts(section["texts"], ("title", "article_body"))[language]
        public.append({
            "section_id": section["section_id"], "position": section["position"],
            "title": translation["title"], "article_body": translation["article_body"],
            "read_at": parse_datetime(section["read_at"]) if section["read_at"] else None,
        })
    state = reading_state(len(public), sum(row["read_at"] is not None for row in public))
    common = {"topic_id": str(snapshot["pk"]), "language": language, "progress_generation": str(snapshot["progress_generation"]), "reading": state}
    if section_id is None:
        return {**common, "title": titles[language]["title"], "sections": [
            {key: row[key] for key in ("section_id", "position", "title", "read_at")} for row in public
        ]}
    index = next((i for i, row in enumerate(public) if row["section_id"] == str(section_id)), None)
    if index is None:
        raise Http404
    return {
        **common, "topic_title": titles[language]["title"], "section": public[index],
        "previous_section_id": public[index - 1]["section_id"] if index else None,
        "next_section_id": public[index + 1]["section_id"] if index + 1 < len(public) else None,
    }
