import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, models, transaction

from apps.learning.articles import legacy_article_body
from apps.learning.changes import EditConflict, IncompleteContent, InvalidRevision, edit_topics
from apps.learning.models import Language, Topic, TopicSection, TopicSectionTranslation, TopicStatus
from apps.learning.tests.test_content import bilingual_topic


def add_section(topic, *, position=20, status="published", languages=("ru", "en")):
    topic.refresh_from_db()
    with edit_topics({topic.pk: topic.revision}, using="default"):
        section = TopicSection(topic=topic, position=position, status=status)
        models.Model.save(section)
        for language in languages:
            models.Model.save(TopicSectionTranslation(
                section=section, language=language, title=f"{language} section {position}",
                article_body=f"  {language} body {position}\r\n\n",
            ))
    topic.refresh_from_db()
    return section


def test_legacy_assembly_is_verbatim_for_one_section_and_explicit_for_many():
    first = {"title": "One", "article_body": "  Body\r\n\n"}
    second = {"title": "Two", "article_body": "\nSecond  "}
    assert legacy_article_body([first]) == first["article_body"]
    assert legacy_article_body([first, second]) == "One\n\n  Body\r\n\n\n\nTwo\n\n\nSecond  "


def test_draft_sections_may_be_incomplete_but_published_require_both_languages(bilingual_topic):
    topic = bilingual_topic
    section = add_section(topic, status="draft", languages=("ru",))
    topic.status = "published"
    topic.save()
    before = topic.revision
    section.status = "published"
    with pytest.raises(IncompleteContent) as rejected:
        section.save(expected_revision=before)
    assert (rejected.value.status, rejected.value.error_code) == (400, "incomplete_content")
    section.refresh_from_db()
    topic.refresh_from_db()
    assert section.status == "draft" and topic.revision == before
    TopicSectionTranslation.objects.create(
        section=section, language="en", title="English", article_body="Body", expected_revision=before,
    )
    topic.refresh_from_db()
    section.status = "published"
    section.save(expected_revision=topic.revision)
    topic.refresh_from_db()
    assert topic.revision == before + 2 and topic.status == "published"


@pytest.mark.parametrize("field", ["title", "article_body"])
@pytest.mark.parametrize("language", ["ru", "en"])
def test_incomplete_published_edit_rolls_back_text_and_revision(bilingual_topic, field, language):
    topic = bilingual_topic
    topic.status = "published"
    topic.save()
    translation = topic.sections.get().translations.get(language=language)
    original = (translation.title, translation.article_body, topic.revision)
    setattr(translation, field, " \t\n")
    with pytest.raises(IncompleteContent):
        translation.save(expected_revision=topic.revision)
    translation.refresh_from_db()
    topic.refresh_from_db()
    assert (translation.title, translation.article_body, topic.revision) == original


@pytest.mark.parametrize("operation", ["delete", "draft"])
def test_last_published_section_cannot_disappear_from_published_topic(bilingual_topic, operation):
    topic = bilingual_topic
    topic.status = "published"
    topic.save()
    section = topic.sections.get()
    revision = topic.revision
    with pytest.raises(IncompleteContent):
        if operation == "delete":
            section.delete(expected_revision=revision)
        else:
            section.status = "draft"
            section.save(expected_revision=revision)
    topic.refresh_from_db()
    section = topic.sections.get()
    assert section.status == "published" and topic.revision == revision
    with edit_topics({topic.pk: revision}, using="default") as locked:
        locked[topic.pk].status = "draft"
        section.status = "draft"
        models.Model.save(section, update_fields=("status",))
    topic.refresh_from_db()
    assert topic.status == "draft" and topic.sections.get().status == "draft"


def test_revision_check_and_immutable_parents_cover_sections_and_translations(bilingual_topic):
    topic = bilingual_topic
    other = Topic.objects.create()
    section = topic.sections.get()
    translation = section.translations.get(language="ru")
    revision = topic.revision
    translation.title = "First edit"
    translation.save(expected_revision=revision)
    with pytest.raises(EditConflict):
        section.position = 40
        section.save(expected_revision=revision)
    topic.refresh_from_db()
    assert topic.revision == revision + 1 and topic.sections.get().position == 10
    section.topic = other
    with pytest.raises(ValidationError) as rejected:
        section.save(expected_revision=other.revision)
    assert rejected.value.code == "immutable_parent"
    another = add_section(topic)
    translation.section = another
    with pytest.raises(ValidationError) as rejected:
        translation.save(expected_revision=topic.revision)
    assert rejected.value.code == "immutable_parent"
    assert TopicSectionTranslation.objects.get(pk=translation.pk).title == "First edit"


def test_position_swap_is_deferred_preserves_ids_and_bumps_one_revision(bilingual_topic):
    topic = bilingual_topic
    first = topic.sections.get()
    second = add_section(topic)
    revision = topic.revision
    with edit_topics({topic.pk: revision}, using="default"):
        first.position, second.position = second.position, first.position
        models.Model.save(first, update_fields=("position",))
        models.Model.save(second, update_fields=("position",))
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS "learning_section_position_unique" IMMEDIATE')
    topic.refresh_from_db()
    assert list(topic.sections.values_list("pk", "position")) == [(second.pk, 10), (first.pk, 20)]
    assert topic.revision == revision + 1


def test_database_constraints_cannot_store_duplicate_position_or_invalid_translation(bilingual_topic):
    topic = bilingual_topic
    section = topic.sections.get()
    for row, constraint in [
        (TopicSection(topic=topic, position=0), "learning_section_position_positive"),
        (TopicSection(topic=topic, position=30, status="invalid"), "learning_section_status_valid"),
        (TopicSection(topic=topic, position=10), "learning_section_position_unique"),
        (TopicSectionTranslation(section=section, language="de"), "learning_section_translation_language_valid"),
        (TopicSectionTranslation(section=section, language="ru"), "learning_section_translation_unique"),
    ]:
        with pytest.raises(IntegrityError) as rejected, transaction.atomic():
            models.Model.save(row)
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert rejected.value.__cause__.diag.constraint_name == constraint


def test_bulk_writes_and_missing_revision_are_rejected_and_legacy_body_is_read_only(bilingual_topic):
    section = bilingual_topic.sections.get()
    translation = section.translations.get(language="ru")
    for obj in (section, translation):
        with pytest.raises(InvalidRevision):
            obj.save()
        manager = type(obj).objects
        for write in (lambda: manager.filter(pk=obj.pk).update(), lambda: manager.all().delete(),
                      lambda: manager.bulk_create([]), lambda: manager.bulk_update([], ["id"])):
            with pytest.raises(ValidationError):
                write()
    legacy = bilingual_topic.translations.get(language="ru")
    legacy.article_body = "Must not replace sections"
    with pytest.raises(ValidationError, match="Legacy"):
        legacy.save()
    with pytest.raises(ValidationError, match="Legacy"):
        bilingual_topic.translations.update(article_body="Must not replace sections")
    with pytest.raises(ValidationError, match="Legacy"):
        type(legacy).objects.bulk_create([legacy], update_conflicts=True, unique_fields=["topic", "language"], update_fields=["article_body"])
