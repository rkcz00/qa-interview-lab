from datetime import datetime, timezone
from fractions import Fraction

import pytest
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from apps.accounts.models import User
from apps.assessments.completion import completion_progress, completion_value
from apps.assessments.models import TopicProgress, TopicSectionProgress, UserProgressState
from apps.assessments.progress import user_progress
from apps.assessments.reading import (
    SectionReadRequired, article_contribution, public_reading, reading_snapshot, reading_state,
    require_topic_read, save_section_read,
)
from apps.learning.models import Topic, TopicStatus
from apps.learning.tests.test_content import bilingual_topic
from apps.learning.tests.test_sections import add_section
from tests.api.test_progress import store_historical_result


FIRST = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("total,read,expected", [(0, 0, 0), (1, 0, 0), (1, 1, 30), (2, 1, 15), (3, 1, 10), (7, 1, Fraction(30, 7))])
def test_article_fraction_and_aggregate_read(total, read, expected):
    assert article_contribution(total, read) == expected
    state = reading_state(total, read)
    assert state["is_read"] is (total > 0 and read == total)
    assert set(state) == {"total_sections", "read_sections", "is_read", "completion_contribution"}


@pytest.mark.parametrize("total,read", [(0, 1), (1, 2), (-1, 0), (1, -1), (True, 1), (1, False), (2.0, 1), ("2", 1)])
def test_invalid_section_counts_are_not_hidden(total, read):
    with pytest.raises(ValueError):
        article_contribution(total, read)


def test_partial_completion_keeps_activity_weights_and_zero_branches():
    assert completion_value(False, ("passed",), total_sections=2, read_sections=1) == 85
    assert completion_value(False, (), total_sections=2, read_sections=1) == 15
    assert completion_value(False, (), total_sections=0, read_sections=0) == 0
    assert completion_value(True, ("passed", "unattempted"), total_sections=2, read_sections=2) == 65


def test_section_progress_uniqueness_first_date_and_protected_content(bilingual_topic):
    section = bilingual_topic.sections.get()
    user = User.objects.create_user("section-owner@example.invalid")
    other = User.objects.create_user("section-other@example.invalid")
    first = TopicSectionProgress.objects.create(user=user, section=section, read_at=FIRST)
    with pytest.raises(IntegrityError), transaction.atomic():
        TopicSectionProgress.objects.create(user=user, section=section)
    TopicSectionProgress.objects.create(user=other, section=section)
    mark = save_section_read(user.pk, section)
    assert mark.pk == first.pk and mark.read_at == FIRST
    with pytest.raises(ProtectedError):
        section.delete(expected_revision=bilingual_topic.revision)
    with pytest.raises(ProtectedError):
        bilingual_topic.delete()
    other.delete()
    assert TopicSectionProgress.objects.count() == 1
    assert TopicSectionProgress.objects.get().read_at == FIRST


def test_dynamic_read_mastery_and_completion_preserve_old_dates_and_results(bilingual_topic):
    topic = bilingual_topic
    user = User.objects.create_user("dynamic-reader@example.invalid")
    topic.status = TopicStatus.PUBLISHED
    topic.save()
    first = topic.sections.get()
    TopicProgress.objects.create(user=user, topic=topic, article_read_at=FIRST)
    store_historical_result(user, topic, 4, 5)
    assert user_progress(user.pk)[0]["mastered"] is False  # Legacy row is not an authorization gate.
    TopicSectionProgress.objects.create(user=user, section=first, read_at=FIRST)
    assert completion_progress(user.pk)["topics"][0]["completion_progress"] == 100
    second = add_section(topic)
    value = completion_progress(user.pk)["topics"][0]
    assert value["completion_progress"] == 85 and value["article_read_at"] is None and not value["mastered"]
    with pytest.raises(SectionReadRequired):
        require_topic_read(user.pk, topic.pk)
    topic.refresh_from_db()
    second.status = TopicStatus.DRAFT
    second.save(expected_revision=topic.revision)
    assert completion_progress(user.pk)["topics"][0]["mastered"] is True
    assert TopicSectionProgress.objects.count() == 1
    topic.refresh_from_db()
    second.status = TopicStatus.PUBLISHED
    second.save(expected_revision=topic.revision)
    assert completion_progress(user.pk)["topics"][0]["mastered"] is False
    save_section_read(user.pk, second)
    require_topic_read(user.pk, topic.pk)
    assert completion_progress(user.pk)["topics"][0]["mastered"] is True
    first_mark = TopicSectionProgress.objects.get(user=user, section=first)
    assert first_mark.read_at == FIRST and TopicProgress.objects.get(user=user).article_read_at == FIRST
    topic.refresh_from_db()
    second.status = TopicStatus.DRAFT
    second.save(expected_revision=topic.revision)
    assert TopicSectionProgress.objects.count() == 2
    assert completion_progress(user.pk)["topics"][0]["completion_progress"] == 100
    topic.refresh_from_db()
    second.status = TopicStatus.PUBLISHED
    second.save(expected_revision=topic.revision)
    assert completion_progress(user.pk)["topics"][0]["mastered"] is True
    topic.refresh_from_db()
    topic.status = TopicStatus.DRAFT
    topic.save()
    assert completion_progress(user.pk)["topics"] == []
    assert user_progress(user.pk)[0]["mastered"] is True


def test_reading_snapshot_is_one_statement_for_generation_content_and_own_marks(bilingual_topic, django_assert_num_queries):
    topic = bilingual_topic
    second = add_section(topic, position=5)
    add_section(topic, position=30, status="draft", languages=("ru",))
    topic.status = TopicStatus.PUBLISHED
    topic.save()
    user = User.objects.create_user("snapshot-reader@example.invalid")
    other = User.objects.create_user("snapshot-other@example.invalid")
    TopicSectionProgress.objects.create(user=user, section=second, read_at=FIRST)
    TopicSectionProgress.objects.create(user=other, section=topic.sections.get(position=10))
    with django_assert_num_queries(1):
        snapshot = reading_snapshot(user.pk, topic.pk)
        ru = public_reading(snapshot, "ru")
    en = public_reading(snapshot, "en", second.pk)
    assert ru["reading"] == {"total_sections": 2, "read_sections": 1, "is_read": False, "completion_contribution": 15}
    assert [row["position"] for row in ru["sections"]] == [5, 10]
    assert ru["progress_generation"] == "1" and not UserProgressState.objects.exists()
    assert all(set(row) == {"section_id", "position", "title", "read_at"} for row in ru["sections"])
    assert en["section"]["read_at"] == FIRST and en["previous_section_id"] is None
    assert en["next_section_id"] == str(topic.sections.get(position=10).pk)
    assert en["section"]["title"] == "en section 5"


@pytest.mark.django_db
def test_draft_without_sections_does_not_become_read_from_a_legacy_date():
    user = User.objects.create_user("empty-legacy-reader@example.invalid")
    topic = Topic.objects.create()
    TopicProgress.objects.create(user=user, topic=topic, article_read_at=FIRST)
    assert user_progress(user.pk) == [{"topic_id": str(topic.pk), "article_read_at": None, "best_result": None, "mastered": False}]


def test_section_read_response_failure_rolls_back_both_marks(bilingual_topic, monkeypatch):
    from django.test import Client
    from apps.assessments.serializers import SectionReadSerializer
    topic = bilingual_topic
    topic.status = TopicStatus.PUBLISHED
    topic.save()
    user = User.objects.create_user("section-rollback@example.invalid")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    token = client.get("/api/v1/auth/csrf/").json()["data"]["csrf_token"]
    seen = []
    def broken(self, value):
        seen.append(TopicSectionProgress.objects.filter(user=user).count())
        raise RuntimeError("Synthetic response failure")
    monkeypatch.setattr(SectionReadSerializer, "to_representation", broken)
    response = client.post(f"/api/v1/topics/{topic.pk}/sections/{topic.sections.get().pk}/read/", {},
                           content_type="application/json", HTTP_X_CSRFTOKEN=token, HTTP_X_PROGRESS_GENERATION="1")
    assert response.status_code == 500 and response.json()["error"]["code"] == "internal_error"
    assert seen == [1] and not TopicSectionProgress.objects.exists() and not TopicProgress.objects.exists()
