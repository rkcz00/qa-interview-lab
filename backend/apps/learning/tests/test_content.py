import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from apps.assessments.models import Choice, ChoiceTranslation, Question, QuestionTranslation, QuestionType
from apps.learning.models import (
    Language,
    Term,
    TermTranslation,
    Topic,
    TopicStatus,
    TopicTranslation,
    require_translations,
)


@pytest.fixture
def bilingual_topic(db):
    topic = Topic.objects.create()
    for language in Language.values:
        TopicTranslation.objects.create(
            topic=topic, language=language, title=f"{language} title", article_body=f"{language} article"
        )

    for position in (20, 10):
        term = Term.objects.create(topic=topic, position=position)
        for language in Language.values:
            TermTranslation.objects.create(
                term=term, language=language, name=f"{language} term {position}", definition=f"{language} definition"
            )

    for question_type, position, correct_positions in (
        (QuestionType.SINGLE_CHOICE, 20, {10}),
        (QuestionType.MULTIPLE_CHOICE, 10, {10, 20}),
    ):
        question = Question.objects.create(topic=topic, position=position, question_type=question_type)
        for language in Language.values:
            QuestionTranslation.objects.create(
                question=question, language=language, text=f"{language} question {position}"
            )
        for choice_position in (30, 20, 10):
            choice = Choice.objects.create(
                question=question, position=choice_position, is_correct=choice_position in correct_positions
            )
            for language in Language.values:
                ChoiceTranslation.objects.create(
                    choice=choice, language=language, text=f"{language} choice {choice_position}"
                )
    return topic


@pytest.fixture
def translation_sources(bilingual_topic):
    question = bilingual_topic.questions.first()
    return {
        "article": bilingual_topic.translations,
        "term": bilingual_topic.terms.first().translations,
        "question": question.translations,
        "choice": question.choices.first().translations,
    }


def assert_publication_rejected(topic, code):
    topic.status = TopicStatus.PUBLISHED
    with pytest.raises(ValidationError) as rejected:
        topic.save(update_fields=("status",))
    assert rejected.value.code == code
    topic.refresh_from_db()
    assert topic.status == TopicStatus.DRAFT


def test_translation_validation_without_database():
    translations = [QuestionTranslation(language=language, text=f"{language} text") for language in Language.values]
    require_translations(translations, fields=("text",), label="Вопрос")
    with pytest.raises(ValidationError) as rejected:
        require_translations(translations[:1], fields=("text",), label="Вопрос")
    assert rejected.value.code == "missing_translation"


@pytest.mark.parametrize("text", ["", " \t\n\u00a0"])
def test_blank_text_fails_domain_validation(text):
    translations = [
        QuestionTranslation(language=Language.RU, text="Вопрос"),
        QuestionTranslation(language=Language.EN, text=text),
    ]
    with pytest.raises(ValidationError) as rejected:
        require_translations(translations, fields=("text",), label="Вопрос")
    assert rejected.value.code == "blank_translation"


def test_content_models_are_registered_with_read_only_topic_status():
    models = (Topic, TopicTranslation, Term, TermTranslation, Question, QuestionTranslation, Choice, ChoiceTranslation)
    for model in models:
        assert admin.site.is_registered(model)
    assert "status" in admin.site.get_model_admin(Topic).readonly_fields


def test_complete_bilingual_topic_can_store_published_status(bilingual_topic):
    assert bilingual_topic.status == TopicStatus.DRAFT
    bilingual_topic.status = TopicStatus.PUBLISHED
    bilingual_topic.full_clean()
    bilingual_topic.save()
    bilingual_topic.refresh_from_db()
    assert bilingual_topic.status == TopicStatus.PUBLISHED

    bilingual_topic.status = TopicStatus.DRAFT
    bilingual_topic.save(update_fields=("status",))
    bilingual_topic.refresh_from_db()
    assert bilingual_topic.status == TopicStatus.DRAFT


@pytest.mark.django_db
def test_new_topics_start_as_drafts_and_cannot_skip_validation():
    topic = Topic.objects.create()
    assert topic.status == TopicStatus.DRAFT
    assert not topic.translations.exists()

    with pytest.raises(ValidationError, match="Draft"):
        Topic.objects.create(status=TopicStatus.PUBLISHED)
    with pytest.raises(ValidationError, match="Draft"):
        Topic.objects.bulk_create([Topic(status=TopicStatus.PUBLISHED)])
    with pytest.raises(ValidationError, match="Статус"):
        Topic.objects.filter(pk=topic.pk).update(status=TopicStatus.PUBLISHED)
    assert_publication_rejected(topic, "missing_translation")


@pytest.mark.parametrize("language", Language.values)
@pytest.mark.parametrize("source", ["article", "term", "question", "choice"])
def test_missing_translation_prevents_publication(bilingual_topic, translation_sources, source, language):
    translation_sources[source].get(language=language).delete()
    assert_publication_rejected(bilingual_topic, "missing_translation")


@pytest.mark.parametrize(
    ("source", "field"),
    [
        ("article", "title"),
        ("article", "article_body"),
        ("term", "name"),
        ("term", "definition"),
        ("question", "text"),
        ("choice", "text"),
    ],
)
def test_whitespace_translation_prevents_publication(bilingual_topic, translation_sources, source, field):
    translation = translation_sources[source].get(language=Language.EN)
    setattr(translation, field, " \t\n")
    translation.save(update_fields=(field,))
    assert_publication_rejected(bilingual_topic, "blank_translation")


@pytest.mark.parametrize(("relation", "error_code"), [("questions", "missing_questions"), ("terms", "missing_terms")])
def test_topic_requires_questions_and_terms(bilingual_topic, relation, error_code):
    getattr(bilingual_topic, relation).all().delete()
    assert_publication_rejected(bilingual_topic, error_code)


def test_question_requires_two_choices(bilingual_topic):
    question = bilingual_topic.questions.get(question_type=QuestionType.SINGLE_CHOICE)
    question.choices.filter(is_correct=False).delete()
    assert_publication_rejected(bilingual_topic, "insufficient_choices")


@pytest.mark.parametrize(
    ("question_type", "correct_count"),
    [(QuestionType.SINGLE_CHOICE, 0), (QuestionType.SINGLE_CHOICE, 2), (QuestionType.MULTIPLE_CHOICE, 1)],
)
def test_question_requires_correct_number_of_keys(bilingual_topic, question_type, correct_count):
    question = bilingual_topic.questions.get(question_type=question_type)
    choice_ids = list(question.choices.values_list("id", flat=True))
    question.choices.update(is_correct=False)
    question.choices.filter(pk__in=choice_ids[:correct_count]).update(is_correct=True)
    assert_publication_rejected(bilingual_topic, "invalid_correct_count")


def test_saved_status_uses_current_translations(bilingual_topic):
    cached = Topic.objects.prefetch_related("translations").get(pk=bilingual_topic.pk)
    TopicTranslation.objects.get(topic=bilingual_topic, language=Language.EN).delete()
    assert_publication_rejected(cached, "missing_translation")


@pytest.mark.parametrize("article_language", Language.values)
@pytest.mark.parametrize("test_language", Language.values)
def test_article_and_test_languages_resolve_independently(bilingual_topic, article_language, test_language):
    article = bilingual_topic.translations.get(language=article_language)
    assert article.topic_id == bilingual_topic.pk
    assert article.article_body == f"{article_language} article"
    assert list(bilingual_topic.terms.values_list("position", flat=True)) == [10, 20]
    for term in bilingual_topic.terms.all():
        translation = term.translations.get(language=article_language)
        assert translation.term_id == term.pk
        assert translation.name == f"{article_language} term {term.position}"

    assert list(bilingual_topic.questions.values_list("position", flat=True)) == [10, 20]
    for question in bilingual_topic.questions.all():
        translation = question.translations.get(language=test_language)
        assert translation.question_id == question.pk
        assert translation.text == f"{test_language} question {question.position}"
        assert list(question.choices.values_list("position", flat=True)) == [10, 20, 30]
        for choice in question.choices.all():
            translation = choice.translations.get(language=test_language)
            assert translation.choice_id == choice.pk
            assert translation.text == f"{test_language} choice {choice.position}"
            assert translation.choice.is_correct == choice.is_correct
    assert not hasattr(ChoiceTranslation, "is_correct")


@pytest.mark.parametrize("source", ["article", "term", "question", "choice"])
def test_database_enforces_unique_translations_and_supported_languages(translation_sources, source):
    translations = translation_sources[source]
    duplicate = translations.get(language=Language.RU)
    duplicate.pk = None
    with pytest.raises(IntegrityError) as rejected, transaction.atomic():
        duplicate.save(force_insert=True)
    assert rejected.value.__cause__.diag.constraint_name.endswith("_translation_unique")

    with pytest.raises(IntegrityError) as rejected, transaction.atomic():
        translations.filter(language=Language.EN).update(language="de")
    assert rejected.value.__cause__.diag.constraint_name.endswith("_translation_language_valid")
    assert set(translations.values_list("language", flat=True)) == set(Language.values)


@pytest.mark.django_db
def test_database_checks_status_question_type_position_and_foreign_key():
    with pytest.raises(IntegrityError) as rejected, transaction.atomic():
        Topic._base_manager.bulk_create([Topic(status="unknown")])
    assert rejected.value.__cause__.diag.constraint_name == "learning_topic_status_valid"

    topic = Topic.objects.create()
    with pytest.raises(IntegrityError) as rejected, transaction.atomic():
        Question.objects.create(topic=topic, question_type="unknown", position=0)
    assert rejected.value.__cause__.diag.constraint_name == "assessments_question_type_valid"

    with pytest.raises(IntegrityError), transaction.atomic():
        Term.objects.create(topic=topic, position=-1)
    with pytest.raises(IntegrityError), transaction.atomic():
        Term.objects.create(topic_id=-1, position=0)
        connection.check_constraints()
