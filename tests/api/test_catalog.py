import httpx
import pytest
from django.contrib.sessions.models import Session

from apps.accounts.models import User
from apps.learning.models import Language, Term, TermTranslation, Topic, TopicStatus, TopicTranslation
from apps.learning.tests.test_content import bilingual_topic, create_bilingual_topic

from .test_registration import assert_error, bootstrap
from .test_session import TEST_PASSWORD, assert_account, login


TOPICS_URL = "/api/v1/topics/"


def article_url(topic_id):
    return f"{TOPICS_URL}{topic_id}/"


def terms_url(topic_id):
    return f"{article_url(topic_id)}terms/"


def sign_in(client, user):
    assert_account(login(client, user.email, bootstrap(client)), user)


@pytest.fixture
def learner_client(api_client):
    sign_in(api_client, User.objects.create_user("catalog-learner@example.invalid", TEST_PASSWORD))
    return api_client


def publish(topic):
    topic.status = TopicStatus.PUBLISHED
    topic.save(update_fields=("status",))


def assert_data(response, expected):
    assert response.status_code == 200
    assert response.headers["Content-Type"].split(";")[0] == "application/json"
    if response.json() != {"data": expected}:
        pytest.fail("Catalog response did not match the public data contract", pytrace=False)


def test_anonymous_requests_require_a_session(api_client):
    for url in (TOPICS_URL, article_url(1), terms_url(1)):
        assert_error(api_client.get(url), 403, "authentication_required")


def test_catalog_only_lists_published_topics_in_a_stable_order(learner_client, bilingual_topic):
    first = bilingual_topic
    second = create_bilingual_topic()
    for language in Language.values:
        second.translations.filter(language=language).update(title=f"{language} second title")
    draft = Topic.objects.create()
    TopicTranslation.objects.create(topic=draft, language=Language.RU, title="Hidden title")
    assert_data(learner_client.get(TOPICS_URL), [])

    publish(second)
    publish(first)
    for language in Language.values:
        expected = [
            {"topic_id": str(first.pk), "title": f"{language} title"},
            {"topic_id": str(second.pk), "title": f"{language} second title"},
        ]
        assert_data(learner_client.get(TOPICS_URL, params={"language": language}), expected)
        if language == Language.RU:
            assert_data(learner_client.get(TOPICS_URL), expected)


def test_article_and_glossary_use_the_requested_language_and_order(learner_client, bilingual_topic):
    topic = bilingual_topic
    first = topic.terms.get(position=10)
    last = topic.terms.get(position=20)
    tied = Term.objects.create(topic=topic, position=10)
    for language in Language.values:
        TermTranslation.objects.create(term=tied, language=language, name=f"{language} tie", definition=f"{language} definition")
    publish(topic)

    def article(language):
        return {
            "topic_id": str(topic.pk), "title": f"{language} title",
            "language": language, "article_body": f"{language} article",
        }

    def glossary(language):
        return [
            {
                "term_id": str(term.pk), "position": term.position, "language": language,
                "name": f"{language} {name}", "definition": f"{language} definition",
            }
            for term, name in ((first, "term 10"), (tied, "tie"), (last, "term 20"))
        ]

    assert_data(learner_client.get(article_url(topic.pk), params={"language": "en"}), article("en"))
    assert_data(learner_client.get(terms_url(topic.pk)), glossary("ru"))
    assert_data(learner_client.get(terms_url(topic.pk), params={"language": "en"}), glossary("en"))
    assert_data(learner_client.get(article_url(topic.pk)), article("ru"))


def test_draft_unpublished_and_missing_topics_have_the_same_not_found_response(api_client, bilingual_topic):
    editor = User.objects.create_superuser("catalog-staff@example.invalid", TEST_PASSWORD)
    sign_in(api_client, editor)
    published = bilingual_topic
    draft = create_bilingual_topic()
    publish(published)

    assert_data(api_client.get(TOPICS_URL), [{"topic_id": str(published.pk), "title": "ru title"}])
    expected = None
    for topic_id in (draft.pk, draft.pk + 1_000_000, "no-such-topic", "9223372036854775808"):
        for url in (article_url(topic_id), terms_url(topic_id)):
            response = api_client.get(url)
            assert_error(response, 404, "not_found")
            if expected is None:
                expected = response.json()
            assert response.json() == expected

    for url in (article_url(draft.pk), terms_url(draft.pk)):
        assert_error(api_client.get(url, params={"language": "de"}), 404, "not_found")

    assert api_client.get(article_url(published.pk)).status_code == 200
    assert api_client.get(terms_url(published.pk)).status_code == 200
    published.status = TopicStatus.DRAFT
    published.save(update_fields=("status",))
    assert_data(api_client.get(TOPICS_URL), [])
    for url in (article_url(published.pk), terms_url(published.pk)):
        response = api_client.get(url)
        assert_error(response, 404, "not_found")
        assert response.json() == expected


def test_catalog_rejects_unsupported_query_and_write_methods(learner_client, bilingual_topic):
    publish(bilingual_topic)
    token = bootstrap(learner_client)
    for url in (TOPICS_URL, article_url(bilingual_topic.pk), terms_url(bilingual_topic.pk)):
        for query in ("language=de", "language=", "language=RU", "language=ru&language=en", "page=2"):
            assert_error(learner_client.get(f"{url}?{query}"), 400, "validation_error")
        response = learner_client.post(url, json={}, headers={"X-CSRFToken": token})
        assert_error(response, 405, "method_not_allowed")
        assert response.headers["Allow"] == "GET"


def test_shared_catalog_does_not_expose_accounts_or_change_sessions(learner_client, bilingual_topic):
    topic = bilingual_topic
    publish(topic)
    revision = topic.revision
    other = User.objects.create_user("other-catalog-learner@example.invalid", TEST_PASSWORD)

    with httpx.Client(base_url=learner_client.base_url, trust_env=False) as other_client:
        sign_in(other_client, other)
        sessions_before = dict(Session.objects.values_list("session_key", "session_data"))
        for url in (TOPICS_URL, article_url(topic.pk), terms_url(topic.pk)):
            first_response = learner_client.get(url, params={"language": "en"})
            second_response = other_client.get(url, params={"language": "en"})
            assert first_response.status_code == second_response.status_code == 200
            if first_response.json() != second_response.json() or other.email in first_response.text:
                pytest.fail("Content response exposed account-specific data", pytrace=False)
            assert_error(learner_client.get(url, params={"user_id": other.pk}), 400, "validation_error")

    if dict(Session.objects.values_list("session_key", "session_data")) != sessions_before:
        pytest.fail("Catalog reads modified session data", pytrace=False)
    topic.refresh_from_db()
    assert topic.revision == revision
