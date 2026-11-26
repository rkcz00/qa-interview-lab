from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from django.contrib.auth.models import Group
from django.db import models

from apps.learning.changes import edit_topics
from apps.learning.models import Topic, TopicSection, TopicSectionTranslation
from apps.learning.tests.test_content import bilingual_topic
from apps.learning.tests.test_sections import add_section
from .pg_locks import wait_for_lock_waiters
from .test_catalog import learner_client, publish
from .test_content_admin import (
    RevisionFields, admin_url, assert_error as admin_error, content_editor, editor, post, sign_in,
)
from .test_registration import assert_error, bootstrap


def sections_url(topic):
    return f"/api/v1/topics/{topic.pk}/sections/"


def test_sections_anonymous_and_method_contract(api_client):
    assert_error(api_client.get("/api/v1/topics/1/sections/?language=de"), 403, "authentication_required")


def test_sections_only_publish_ordered_public_translations_and_keep_legacy_dto(learner_client, bilingual_topic):
    topic = bilingual_topic
    earlier = add_section(topic, position=5)
    add_section(topic, position=30, status="draft", languages=("ru",))
    publish(topic)
    for language in ("ru", "en"):
        response = learner_client.get(sections_url(topic), params={"language": language})
        assert response.status_code == 200 and "no-store" in response.headers["Cache-Control"]
        article = response.json()["data"]
        assert set(article) == {"topic_id", "title", "language", "sections"}
        assert (article["topic_id"], article["title"], article["language"]) == (str(topic.pk), f"{language} title", language)
        rows = article["sections"]
        assert [row["position"] for row in rows] == [5, 10] and rows[0]["section_id"] == str(earlier.pk)
        assert all(set(row) == {"section_id", "position", "title", "article_body"} for row in rows)
        assert rows[0]["article_body"] == f"  {language} body 5\r\n\n"
        legacy = learner_client.get(f"/api/v1/topics/{topic.pk}/", params={"language": language}).json()["data"]
        assert set(legacy) == {"topic_id", "title", "language", "article_body"}
        assert legacy["article_body"] == "\n\n".join(row["title"] + "\n\n" + row["article_body"] for row in rows)
    assert not topic.progress.exists()  # Neither GET is a Read write.


def test_single_section_legacy_body_is_verbatim_and_legacy_copy_is_ignored(learner_client, bilingual_topic):
    topic = bilingual_topic
    translation = topic.sections.get().translations.get(language="ru")
    translation.article_body = "  New section body\r\n\n"
    translation.save(expected_revision=topic.revision)
    topic.refresh_from_db()
    publish(topic)
    assert topic.translations.get(language="ru").article_body == "ru article"
    assert learner_client.get(f"/api/v1/topics/{topic.pk}/").json()["data"]["article_body"] == translation.article_body


@pytest.mark.parametrize("query", ["language=", "language=de", "language=ru&language=en", "unknown=ru"])
def test_sections_reject_invalid_query_without_fallback(learner_client, bilingual_topic, query):
    publish(bilingual_topic)
    assert_error(learner_client.get(sections_url(bilingual_topic) + "?" + query), 400, "validation_error")


def test_sections_draft_missing_invalid_id_and_unsafe_method(learner_client, bilingual_topic):
    for topic_id in (str(bilingual_topic.pk), "0", "-1", "invalid", "9999999999999999999999999999"):
        assert_error(learner_client.get(f"/api/v1/topics/{topic_id}/sections/"), 404, "not_found")
    assert_error(learner_client.get(sections_url(bilingual_topic) + "?language=de"), 404, "not_found")
    publish(bilingual_topic)
    response = learner_client.post(sections_url(bilingual_topic), json={}, headers={"X-CSRFToken": bootstrap(learner_client)})
    assert_error(response, 405, "method_not_allowed")


def test_corrupt_published_translation_returns_safe_500_not_partial_or_fallback(learner_client, bilingual_topic):
    publish(bilingual_topic)
    translation = bilingual_topic.sections.get().translations.get(language="en")
    translation.article_body = ""
    models.Model.save(translation, update_fields=("article_body",))  # Deliberate corrupt fixture, not an application writer.
    for suffix in ("/sections/", "/"):
        response = learner_client.get(f"/api/v1/topics/{bilingual_topic.pk}" + suffix)
        assert_error(response, 500, "internal_error")
        assert set(response.json()) == {"error"}
        assert set(response.json()["error"]) == {"code", "message"}


def test_sections_get_waits_for_one_consistent_committed_tree(learner_client, bilingual_topic):
    topic = bilingual_topic
    add_section(topic)
    publish(topic)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with edit_topics({topic.pk: topic.revision}, using="default"):
            response = pool.submit(learner_client.get, sections_url(topic))
            wait_for_lock_waiters("learning_topic", 1)
            topic.translations.filter(language="ru").update(title="Committed title")
            for section in topic.sections.all():
                translation = section.translations.get(language="ru")
                translation.article_body = "Committed " + str(section.position)
                models.Model.save(translation, update_fields=("article_body",))
        article = response.result(timeout=15).json()["data"]
    assert article["title"] == "Committed title"
    assert [row["article_body"] for row in article["sections"]] == ["Committed 10", "Committed 20"]


def test_section_edit_add_reorder_and_unpublish_preserve_first_read_mastery_and_snapshot(learner_client, bilingual_topic):
    from apps.assessments.models import Attempt
    from .test_attempts import correct_answers, data, post as api_post, start, submit_url
    topic = bilingual_topic
    publish(topic)
    data(api_post(learner_client, f"/api/v1/topics/{topic.pk}/read/", {}))
    completed = start(learner_client, topic, "ru")
    data(api_post(learner_client, submit_url(completed["attempt_id"]), {"language": "ru", "answers": correct_answers(completed)}))
    pending = start(learner_client, topic, "en")
    snapshot = Attempt.objects.get(pk=pending["attempt_id"]).content_snapshot
    before = learner_client.get("/api/v1/progress/").json()
    assert before["data"][0]["mastered"] is True
    first = topic.sections.get()
    translation = first.translations.get(language="ru")
    translation.article_body = "Edited body after Read"
    translation.save(expected_revision=topic.revision)
    second = add_section(topic, position=5)
    with edit_topics({topic.pk: topic.revision}, using="default"):
        first.position, second.position = second.position, first.position
        models.Model.save(first, update_fields=("position",))
        models.Model.save(second, update_fields=("position",))
    assert learner_client.get("/api/v1/progress/").json() == before
    topic.refresh_from_db()
    topic.status = "draft"
    topic.save()
    assert learner_client.get("/api/v1/progress/").json() == before
    assert Attempt.objects.get(pk=pending["attempt_id"]).content_snapshot == snapshot
    submitted = data(api_post(learner_client, submit_url(pending["attempt_id"]), {"language": "en", "answers": correct_answers(pending)}))
    assert submitted["result"] == {"correct_count": 2, "total_count": 2, "percentage": 100}
    assert learner_client.get("/api/v1/progress/").json() == before


def section_action(client, topic, sections, action):
    path = admin_url(TopicSection, "changelist")
    selected = [str(section.pk) for section in sections]
    confirmation = post(client, path, {"action": action, "index": "0", "_selected_action": selected})
    assert RevisionFields(confirmation).revisions == [f"{topic.pk}:{topic.revision}"]
    return post(client, path, {"action": action, "confirm": "yes", "_selected_action": selected,
                             "expected_revision": [f"{topic.pk}:{topic.revision}"]})


def test_real_content_admin_sections_permissions_and_atomic_publish(editor, bilingual_topic):
    topic = bilingual_topic
    for model in (TopicSection, TopicSectionTranslation):
        listing = editor.get(admin_url(model, "changelist"))
        assert listing.status_code == 200 and 'value="delete_selected"' not in listing.text
        assert editor.get(admin_url(model, "add")).status_code == 200
        assert editor.get(admin_url(model, "change", model.objects.first())).status_code == 200
    group = Group.objects.get(name="Content Admin")
    assert group.permissions.count() == 13 * 4
    assert not group.permissions.filter(content_type__model__in=("user", "group", "attempt", "topicprogress", "practicesubmission", "userprogressstate")).exists()
    # Create through real Admin, including the revision-bearing parent option.
    response = post(editor, admin_url(TopicSection, "add"), {"topic": f"{topic.pk}:{topic.revision}", "position": 20})
    assert response.status_code == 302
    topic.refresh_from_db()
    section = topic.sections.get(position=20)
    revision = topic.revision
    admin_error(section_action(editor, topic, [section], "publish_selected"), 400, "incomplete_content")
    section.refresh_from_db()
    topic.refresh_from_db()
    assert section.status == "draft" and topic.revision == revision
    for language in ("ru", "en"):
        assert post(editor, admin_url(TopicSectionTranslation, "add"), {
            "section": f"{section.pk}:{topic.revision}", "language": language, "title": language + " title", "article_body": "Body",
        }).status_code == 302
        topic.refresh_from_db()
    assert section_action(editor, topic, [section], "publish_selected").status_code == 302
    section.refresh_from_db()
    assert section.status == "published"
    topic.refresh_from_db()
    revision = topic.revision
    deletion = admin_url(TopicSection, "delete", section)
    assert RevisionFields(editor.get(deletion)).revisions == [str(revision)]
    assert post(editor, deletion, {"post": "yes", "expected_revision": str(revision)}).status_code == 302
    topic.refresh_from_db()
    assert not TopicSection.objects.filter(pk=section.pk).exists() and topic.revision == revision + 1


def test_parallel_section_admin_writes_keep_first_version_and_reject_stale(editor, bilingual_topic):
    topic = bilingual_topic
    translation = topic.sections.get().translations.get(language="en")
    revision = topic.revision
    def update(client, title):
        return post(client, admin_url(TopicSectionTranslation, "change", translation), {
            "expected_revision": revision, "language": "en", "title": title, "article_body": "Unchanged body",
        })
    with httpx.Client(base_url=editor.base_url, trust_env=False) as second_editor:
        sign_in(second_editor, content_editor("sections-second"))
        with ThreadPoolExecutor(max_workers=2) as pool:
            from django.db import transaction
            with transaction.atomic():
                Topic.objects.select_for_update().get(pk=topic.pk)
                first = pool.submit(update, editor, "First section edit")
                wait_for_lock_waiters("learning_topic", 1)
                second = pool.submit(update, second_editor, "Stale section edit")
                wait_for_lock_waiters("learning_topic", 2)
            assert first.result(timeout=15).status_code == 302
            admin_error(second.result(timeout=15), 409, "edit_conflict")
    translation.refresh_from_db()
    topic.refresh_from_db()
    assert translation.title == "First section edit" and topic.revision == revision + 1


def test_admin_legacy_body_is_read_only_and_cannot_replace_section_text(editor, bilingual_topic):
    topic = bilingual_topic
    legacy = topic.translations.get(language="ru")
    url = admin_url(type(legacy), "change", legacy)
    assert 'name="article_body"' not in editor.get(url).text
    assert post(editor, url, {"expected_revision": topic.revision, "language": "ru", "title": "New title", "article_body": "Forged replacement"}).status_code == 302
    legacy.refresh_from_db()
    assert legacy.title == "New title" and legacy.article_body == "ru article"
    assert topic.sections.get().translations.get(language="ru").article_body == "ru article"


@pytest.mark.parametrize("kind", ["position", "language"])
def test_admin_duplicate_section_position_or_language_is_a_form_error_without_a_write(editor, bilingual_topic, kind):
    topic = bilingual_topic
    section = add_section(topic)
    revision = topic.revision
    if kind == "position":
        obj, payload = section, {"position": 10}
    else:
        obj = section.translations.get(language="en")
        payload = {"language": "ru", "title": obj.title, "article_body": obj.article_body}
    response = post(editor, admin_url(type(obj), "change", obj), {"expected_revision": revision, **payload})
    assert response.status_code == 200 and 'class="errorlist"' in response.text
    topic.refresh_from_db()
    obj.refresh_from_db()
    assert topic.revision == revision
    assert (obj.position if kind == "position" else obj.language) == (20 if kind == "position" else "en")


def test_batch_section_publication_rolls_back_every_root(editor, bilingual_topic):
    from apps.learning.tests.test_content import create_bilingual_topic
    first, second = bilingual_topic, create_bilingual_topic()
    complete = add_section(first, status="draft")
    incomplete = add_section(second, status="draft", languages=("ru",))
    revisions = {topic.pk: topic.revision for topic in (first, second)}
    path = admin_url(TopicSection, "changelist")
    response = post(editor, path, {"action": "publish_selected", "confirm": "yes", "_selected_action": [str(complete.pk), str(incomplete.pk)],
                                  "expected_revision": [f"{pk}:{revision}" for pk, revision in revisions.items()]})
    admin_error(response, 400, "incomplete_content")
    assert dict(Topic.objects.filter(pk__in=revisions).values_list("pk", "revision")) == revisions
    complete.refresh_from_db()
    incomplete.refresh_from_db()
    assert complete.status == incomplete.status == "draft"
