from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

import httpx
import pytest
from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group
from django.db import transaction
from django.urls import reverse

from apps.accounts.models import User
from apps.assessments.models import Choice, ChoiceTranslation, Question, QuestionTranslation
from apps.learning.models import Language, Term, TermTranslation, Topic, TopicStatus, TopicTranslation
from apps.learning.tests.test_content import bilingual_topic

from .pg_locks import wait_for_lock_waiters


TEST_PASSWORD = "qil-synthetic-content-admin-passphrase"
CONTENT_MODELS = (Topic, TopicTranslation, Term, TermTranslation, Question, QuestionTranslation, Choice, ChoiceTranslation)


class RevisionFields(HTMLParser):
    def __init__(self, response):
        super().__init__()
        assert response.status_code == 200
        self.revisions = []
        self.options = set()
        self.feed(response.text)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "input" and attributes.get("name") == "expected_revision":
            self.revisions.append(attributes.get("value", ""))
        if tag == "option":
            self.options.add(attributes.get("value"))


def admin_url(model, view, obj=None):
    name = f"admin:{model._meta.app_label}_{model._meta.model_name}_{view}"
    return reverse(name, args=(obj.pk,) if obj is not None else ())


def csrf_header(client):
    token = client.cookies.get(settings.CSRF_COOKIE_NAME)
    if not token:
        pytest.fail("Admin did not issue the expected CSRF cookie", pytrace=False)
    return {"X-CSRFToken": token}


def post(client, url, data):
    return client.post(url, data=data, headers=csrf_header(client), timeout=15)


def sign_in(client, user):
    url = reverse("admin:login")
    assert client.get(url).status_code == 200
    response = post(client, url, {"username": user.email, "password": TEST_PASSWORD, "next": reverse("admin:index")})
    assert response.status_code == 302
    assert response.headers["Location"] == reverse("admin:index")


def content_editor(name):
    user = User.objects.create_user(f"{name}@example.invalid", TEST_PASSWORD, is_staff=True)
    user.groups.add(Group.objects.get(name="Content Admin"))
    assert not user.is_superuser
    return user


@pytest.fixture
def editor(api_client):
    sign_in(api_client, content_editor("content-editor"))
    return api_client


def assert_error(response, status, code):
    assert response.status_code == status
    if f'data-error-code="{code}"' not in response.text:
        pytest.fail(f"Expected Admin error code {code}", pytrace=False)


def confirm_status(client, topics, action="publish_selected"):
    url = admin_url(Topic, "changelist")
    selected = [str(topic.pk) for topic in topics]
    response = post(client, url, {"action": action, "index": "0", "_selected_action": selected})
    expected = RevisionFields(response).revisions
    assert expected == [f"{topic.pk}:{topic.revision}" for topic in sorted(topics, key=lambda topic: topic.pk)]
    return {
        "action": action,
        "confirm": "yes",
        "_selected_action": selected,
        "expected_revision": expected,
    }


def apply_status(client, topics, action="publish_selected"):
    return post(client, admin_url(Topic, "changelist"), confirm_status(client, topics, action))


def edit_article(client, translation, revision, title, body="Article text"):
    return post(client, admin_url(TopicTranslation, "change", translation), {
        "expected_revision": revision, "language": translation.language, "title": title, "article_body": body,
    })


def test_content_admin_has_only_content_permissions_and_admin_access(editor, bilingual_topic):
    group = Group.objects.get(name="Content Admin")
    expected = {
        (model._meta.app_label, model._meta.model_name, f"{action}_{model._meta.model_name}")
        for model in CONTENT_MODELS for action in ("add", "change", "delete", "view")
    }
    assert set(group.permissions.values_list("content_type__app_label", "content_type__model", "codename")) == expected

    index = editor.get(reverse("admin:index"))
    assert index.status_code == 200
    for model in CONTENT_MODELS:
        obj = model.objects.first()
        assert obj is not None
        assert admin_url(model, "changelist") in index.text
        assert editor.get(admin_url(model, "changelist")).status_code == 200
        assert editor.get(admin_url(model, "add")).status_code == 200
        assert editor.get(admin_url(model, "change", obj)).status_code == 200

    target = User.objects.create_user("protected-learner@example.invalid")
    for model in (User, Group):
        assert admin_url(model, "changelist") not in index.text
        assert editor.get(admin_url(model, "changelist")).status_code == 403
        assert editor.get(admin_url(model, "add")).status_code == 403
    for view in ("change", "delete", "history"):
        assert editor.get(admin_url(User, view, target)).status_code == 403
    assert post(editor, admin_url(User, "change", target), {"is_superuser": "on"}).status_code == 403
    target.refresh_from_db()
    assert not target.is_superuser


def test_staff_outside_group_cannot_change_content(api_client, bilingual_topic):
    staff = User.objects.create_user("plain-staff@example.invalid", TEST_PASSWORD, is_staff=True)
    sign_in(api_client, staff)
    url = admin_url(Topic, "change", bilingual_topic)
    assert api_client.get(url).status_code == 403
    assert post(api_client, url, {"expected_revision": bilingual_topic.revision}).status_code == 403


def test_learner_cannot_open_content_admin(api_client, bilingual_topic):
    learner = User.objects.create_user("ordinary-learner@example.invalid", TEST_PASSWORD)
    assert api_client.get(reverse("admin:login")).status_code == 200
    response = api_client.post(
        "/api/v1/auth/login/", json={"email": learner.email, "password": TEST_PASSWORD}, headers=csrf_header(api_client)
    )
    assert response.status_code == 200
    denied = api_client.get(admin_url(Topic, "change", bilingual_topic))
    assert denied.status_code == 302
    assert denied.headers["Location"].startswith(reverse("admin:login"))


def test_draft_additions_and_deletion_bump_topic_revision(editor):
    assert post(editor, admin_url(Topic, "add"), {}).status_code == 302
    topic = Topic.objects.get()
    assert topic.status == TopicStatus.DRAFT and topic.revision == 1

    def add(model, parent, parent_field, **data):
        url = admin_url(model, "add")
        versioned_parent = f"{parent.pk}:{topic.revision}"
        assert versioned_parent in RevisionFields(editor.get(url)).options
        previous = topic.revision
        assert post(editor, url, {parent_field: versioned_parent, **data}).status_code == 302
        topic.refresh_from_db()
        assert topic.revision == previous + 1
        return model.objects.get()

    add(TopicTranslation, topic, "topic", language="ru", title="Черновик", article_body="")
    term = add(Term, topic, "topic", position=0)
    add(TermTranslation, term, "term", language="ru", name="Термин", definition="")
    question = add(Question, topic, "topic", position=0, question_type="single_choice")
    add(QuestionTranslation, question, "question", language="ru", text="Вопрос")
    choice = add(Choice, question, "question", position=0, is_correct="on")
    translation = add(ChoiceTranslation, choice, "choice", language="ru", text="Вариант")

    url = admin_url(ChoiceTranslation, "delete", translation)
    previous = topic.revision
    assert RevisionFields(editor.get(url)).revisions == [str(previous)]
    assert post(editor, url, {"post": "yes", "expected_revision": previous}).status_code == 302
    topic.refresh_from_db()
    assert topic.revision == previous + 1
    assert not ChoiceTranslation.objects.filter(pk=translation.pk).exists()


def test_stale_add_and_delete_do_not_change_content(editor):
    topic = Topic.objects.create()
    add_url = admin_url(TopicTranslation, "add")
    parent = f"{topic.pk}:1"
    assert parent in RevisionFields(editor.get(add_url)).options
    data = {"topic": parent, "language": "ru", "title": "Черновик", "article_body": ""}
    assert post(editor, add_url, data).status_code == 302
    article = topic.translations.get()
    assert_error(post(editor, add_url, data), 409, "edit_conflict")

    delete_url = admin_url(TopicTranslation, "delete", article)
    assert RevisionFields(editor.get(delete_url)).revisions == ["2"]
    assert edit_article(editor, article, 2, "Changed before deletion").status_code == 302
    audit_count = LogEntry.objects.count()
    assert_error(post(editor, delete_url, {"post": "yes", "expected_revision": "2"}), 409, "edit_conflict")
    topic.refresh_from_db()
    assert topic.revision == 3
    assert topic.translations.get().title == "Changed before deletion"
    assert LogEntry.objects.count() == audit_count


def test_published_topic_allows_complete_edits_and_rolls_back_incomplete_ones(editor, bilingual_topic):
    topic = bilingual_topic
    assert apply_status(editor, [topic]).status_code == 302
    topic.refresh_from_db()
    assert topic.status == TopicStatus.PUBLISHED and topic.revision == 2
    article = topic.translations.get(language=Language.EN)
    url = admin_url(TopicTranslation, "change", article)
    assert RevisionFields(editor.get(url)).revisions == ["2"]
    assert edit_article(editor, article, topic.revision, "Published edit").status_code == 302
    topic.refresh_from_db()
    article.refresh_from_db()
    assert topic.status == TopicStatus.PUBLISHED and topic.revision == 3
    assert article.title == "Published edit"

    audit_count = LogEntry.objects.count()
    response = edit_article(editor, article, topic.revision, "Would be lost", " \t\n")
    assert_error(response, 400, "incomplete_content")
    topic.refresh_from_db()
    article.refresh_from_db()
    assert topic.status == TopicStatus.PUBLISHED and topic.revision == 3
    assert (article.title, article.article_body) == ("Published edit", "Article text")
    assert LogEntry.objects.count() == audit_count

    term_count = topic.terms.count()
    response = post(editor, admin_url(Term, "add"), {"topic": f"{topic.pk}:3", "position": 30})
    assert_error(response, 400, "incomplete_content")
    assert topic.terms.count() == term_count
    assert LogEntry.objects.count() == audit_count

    deletion = admin_url(TopicTranslation, "delete", article)
    assert_error(post(editor, deletion, {"post": "yes", "expected_revision": "3"}), 400, "incomplete_content")
    assert TopicTranslation.objects.filter(pk=article.pk).exists()
    assert LogEntry.objects.count() == audit_count
    topic.refresh_from_db()
    assert topic.revision == 3

    assert apply_status(editor, [topic], "unpublish_selected").status_code == 302
    topic.refresh_from_db()
    assert topic.status == TopicStatus.DRAFT and topic.revision == 4


def test_incomplete_topic_rolls_back_the_entire_publication(editor, bilingual_topic):
    incomplete = Topic.objects.create()
    audit_count = LogEntry.objects.count()
    response = apply_status(editor, [bilingual_topic, incomplete])
    assert_error(response, 400, "incomplete_content")
    for topic in (bilingual_topic, incomplete):
        topic.refresh_from_db()
        assert topic.status == TopicStatus.DRAFT and topic.revision == 1
    assert LogEntry.objects.count() == audit_count


def test_publication_confirmation_rejects_a_stale_revision(editor, bilingual_topic):
    topic = bilingual_topic
    confirmation = confirm_status(editor, [topic])
    article = topic.translations.get(language=Language.EN)
    assert edit_article(editor, article, topic.revision, "New title").status_code == 302
    response = post(editor, admin_url(Topic, "changelist"), confirmation)
    assert_error(response, 409, "edit_conflict")
    topic.refresh_from_db()
    article.refresh_from_db()
    assert topic.status == TopicStatus.DRAFT and topic.revision == 2
    assert article.title == "New title"


def test_two_parallel_admin_writes_preserve_the_first_edit(editor, bilingual_topic):
    topic = bilingual_topic
    article = topic.translations.get(language=Language.EN)
    url = admin_url(TopicTranslation, "change", article)
    with httpx.Client(base_url=editor.base_url, trust_env=False) as second_editor:
        sign_in(second_editor, content_editor("second-editor"))
        first_revision, = RevisionFields(editor.get(url)).revisions
        second_revision, = RevisionFields(second_editor.get(url)).revisions
        assert first_revision == second_revision == str(topic.revision)
        audit_count = LogEntry.objects.count()

        with ThreadPoolExecutor(max_workers=2) as pool:
            with transaction.atomic():
                Topic.objects.select_for_update().get(pk=topic.pk)
                first = pool.submit(edit_article, editor, article, first_revision, "First title", "First body")
                wait_for_lock_waiters("learning_topic", 1)
                second = pool.submit(edit_article, second_editor, article, second_revision, "Second title", "Second body")
                wait_for_lock_waiters("learning_topic", 2)
            assert first.result(timeout=15).status_code == 302
            assert_error(second.result(timeout=15), 409, "edit_conflict")

    topic.refresh_from_db()
    article.refresh_from_db()
    assert topic.revision == 2
    assert (article.title, article.article_body) == ("First title", "First body")
    assert LogEntry.objects.count() == audit_count + 1
