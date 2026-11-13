"""Create real demo content through Admin, then consume it through the learner SPA."""

import json
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit

from playwright.sync_api import expect
import pytest

from tests.e2e.test_auth_ui import check
from tests.e2e.test_learning_ui import signed_in
from tests.e2e.test_assessment_ui import begin, request_post, result
from tests.e2e.test_mvp_acceptance import public_attempt
from tests.e2e.test_progress_ui import card


CONTENT = {"topic": "learning", "topictranslation": "learning", "term": "learning", "termtranslation": "learning",
    "question": "assessments", "questiontranslation": "assessments", "choice": "assessments", "choicetranslation": "assessments"}
DEMO = Path(__file__).resolve().parents[1] / "fixtures/qa_interview_demo.json"


def admin_path(model, object_id=None, operation=None):
    base = "/admin/" + CONTENT[model] + "/" + model + "/"
    return base + (str(object_id) + "/" if object_id else "") + (operation + "/" if operation else "")


def save_form(page, status=302, code=None):
    path = urlsplit(page.url).path
    with page.expect_response(lambda response: urlsplit(response.url).path == path and response.request.method == "POST") as saved:
        page.locator('input[name="_continue"]').click()
    check(saved.value.status == status, "Unexpected Admin form save status")
    if code:
        expect(page.locator('[data-error-code="' + code + '"]')).to_be_visible()
        return None
    expect(page).to_have_url(re.compile(r"/[0-9]+/change/$"))
    return urlsplit(page.url).path.split("/")[-3]


def edit_text(page, fields):
    for field, value in fields.items():
        page.locator("#id_" + field).fill(value)


def answer_demo(page):
    page.locator(".question-card").get_by_role("radio", name="1", exact=True).check()
    page.get_by_role("button", name="Следующий вопрос", exact=True).click()
    for value in ("0", "1", "100", "101"):
        page.locator(".question-card").get_by_role("checkbox", name=value, exact=True).check()
    with page.expect_response(lambda response: response.url.endswith("/submit/")) as submitted:
        page.get_by_role("button", name="Отправить тест", exact=True).click()
    check(submitted.value.status == 200, "Demo attempt must finish through the real API")
    public_attempt(submitted.value.json()["data"])
    result(page)


def change_status(page, topic_id, revision, *, publish=True, status=302, code=None):
    path = admin_path("topic")
    page.goto(path)
    page.locator('input[name="_selected_action"][value="' + topic_id + '"]').check()
    page.locator('select[name="action"]').first.select_option("publish_selected" if publish else "unpublish_selected")
    page.locator('button[name="index"]').first.click()
    check(page.locator('input[name="expected_revision"]').input_value() == topic_id + ":" + str(revision), "Confirmation must carry the current topic revision")
    with page.expect_response(lambda response: urlsplit(response.url).path == path and response.request.method == "POST") as applied:
        page.locator('input[type="submit"][value="Подтвердить"]').click()
    check(applied.value.status == status, "Unexpected Admin publication status")
    if code:
        expect(page.locator('[data-error-code="' + code + '"]')).to_be_visible()
    else:
        expect(page.locator("#changelist")).to_be_visible()


@pytest.fixture
def editor_page(auth_app, auth_browser):
    password = secrets.token_urlsafe(32)
    editor = auth_app.content_admin_data("editor", password=password)
    context = auth_browser.new_context(base_url=auth_app.admin_url, locale="ru-RU")
    page = context.new_page()
    page.set_default_timeout(8_000)
    try:
        page.goto("/admin/login/")
        try:
            page.locator("#id_username").fill(editor["email"])
            page.locator("#id_password").fill(password)
        except Exception:
            pytest.fail("Admin sign-in form failed; credentials were not logged", pytrace=False)
        page.locator('input[type="submit"]').click()
        expect(page).to_have_url(re.compile(r"/admin/$"))
        password = None
        yield page, editor
    finally:
        context.close()


def test_content_admin_demo_publication_and_learner_snapshot(auth_app, auth_browser, auth_page, editor_page):
    admin, editor = editor_page
    data = json.loads(DEMO.read_text(encoding="utf-8"))
    for model in CONTENT:
        expect(admin.locator('#content-main a[href="' + admin_path(model) + '"]').first).to_be_visible()
    forbidden = {"accounts/user": 403, "auth/group": 403, "assessments/attempt": 404, "assessments/topicprogress": 404}
    for model, status in forbidden.items():
        path = "/admin/" + model + "/"
        expect(admin.locator('a[href="' + path + '"]')).to_have_count(0)
        for suffix in ("", "add/", "1/change/", "1/delete/", "1/history/"):
            check(admin.context.request.get(path + suffix).status == status, "Content Admin opened a forbidden Admin section")

    topic_id = None
    try:
        admin.goto(admin_path("topic", operation="add"))
        topic_id = save_form(admin)
        auth_app.content_admin_data("own", topic_id=topic_id)
        revision = 1
        check(admin.locator("#id_expected_revision").input_value() == "1", "New Draft must begin at revision one")

        def add(model, *, parent_field, parent_id, fields):
            nonlocal revision
            admin.goto(admin_path(model, operation="add"))
            value = str(parent_id) + ":" + str(revision)
            admin.locator("#id_" + parent_field).select_option(value)
            for field, text in fields.items():
                locator = admin.locator("#id_" + field)
                if field in {"language", "question_type"}:
                    locator.select_option(text)
                elif field == "is_correct":
                    locator.set_checked(text)
                else:
                    locator.fill(str(text))
            object_id = save_form(admin)
            revision += 1
            check(admin.locator("#id_expected_revision").input_value() == str(revision), "Every child write must increment topic revision")
            return object_id

        articles = {}
        for language, fields in data["translations"].items():
            articles[language] = add("topictranslation", parent_field="topic", parent_id=topic_id, fields={"language": language, **fields})
        for term in data["terms"]:
            term_id = add("term", parent_field="topic", parent_id=topic_id, fields={"position": term["position"]})
            for language, fields in term["translations"].items():
                add("termtranslation", parent_field="term", parent_id=term_id, fields={"language": language, **fields})
        missing = None
        extra_choice = None
        for question in data["questions"]:
            question_id = add("question", parent_field="topic", parent_id=topic_id,
                fields={"position": question["position"], "question_type": question["question_type"]})
            for language, text in question["translations"].items():
                add("questiontranslation", parent_field="question", parent_id=question_id, fields={"language": language, "text": text})
            for choice in question["choices"]:
                choice_id = add("choice", parent_field="question", parent_id=question_id,
                    fields={"position": choice["position"], "is_correct": choice["is_correct"]})
                for language, text in choice["translations"].items():
                    if question["position"] == 20 and choice["position"] == 50 and language == "en":
                        missing = {"language": language, "text": text}
                        extra_choice = choice_id
                    else:
                        add("choicetranslation", parent_field="choice", parent_id=choice_id, fields={"language": language, "text": text})

        before = auth_app.content_admin_data("inspect", topic_id=topic_id)
        change_status(admin, topic_id, revision, status=400, code="incomplete_content")
        check(auth_app.content_admin_data("inspect", topic_id=topic_id) == before, "Rejected publication must roll back revision, content and audit log")
        add("choicetranslation", parent_field="choice", parent_id=extra_choice, fields=missing)
        before = auth_app.content_admin_data("inspect", topic_id=topic_id)
        check(before["model_counts"] == [1, 2, 3, 6, 2, 4, 8, 16], "Demo must contain the complete eight-model bilingual tree")
        change_status(admin, topic_id, revision)
        revision += 1
        published = auth_app.content_admin_data("inspect", topic_id=topic_id)
        check(published["status"] == "published" and published["revision"] == revision, "Full content must publish in one revision")

        learner = auth_page
        signed_in(learner)
        learner.goto("/topics")
        learner.get_by_role("link", name=data["translations"]["ru"]["title"], exact=True).click()
        expect(learner.locator(".article-body")).to_have_text(data["translations"]["ru"]["article_body"])
        expect(learner.locator(".glossary dt")).to_have_text([term["translations"]["ru"]["name"] for term in data["terms"]])
        learner.get_by_role("radio", name="English", exact=True).check()
        expect(learner.locator(".article-body")).to_have_text(data["translations"]["en"]["article_body"])
        expect(learner.locator(".glossary dt")).to_have_text([term["translations"]["en"]["name"] for term in data["terms"]])
        for language in ("ru", "en"):
            article = learner.context.request.get("/api/v1/topics/" + topic_id + "/?language=" + language).json()["data"]
            check(set(article) == {"topic_id", "title", "language", "article_body"}, "Article must contain only public fields")
            terms = learner.context.request.get("/api/v1/topics/" + topic_id + "/terms/?language=" + language).json()["data"]
            check(all(set(term) == {"term_id", "position", "language", "name", "definition"} for term in terms), "Glossary must contain only public fields")
        learner.get_by_role("button", name="Отметить «Прочитано»", exact=True).click()
        expect(learner.get_by_role("button", name="Прочитано", exact=True)).to_be_disabled()
        begin(learner, topic_id, "en")
        answer_demo(learner)
        pending = begin(learner, topic_id, "ru")
        projections = {}
        for language in ("ru", "en"):
            response = learner.context.request.get("/api/v1/attempts/" + pending + "/?language=" + language)
            check(response.status == 200, "Pending attempt must be readable")
            public_attempt(response.json()["data"])
            projections[language] = response.json()
        progress = learner.context.request.get("/api/v1/progress/").json()
        check(progress["data"][0]["mastered"] is True, "Existing mastery is required before unpublication")
        history = learner.context.request.get("/api/v1/attempts/").json()

        # Two real Admin forms preserve the first successful Published edit.
        edit_path = admin_path("topictranslation", articles["en"], "change")
        admin.goto(edit_path)
        second = admin.context.new_page()
        try:
            second.goto(edit_path)
            check(second.locator("#id_expected_revision").input_value() == str(revision), "Parallel form must see the same revision")
            edit_text(admin, {"article_body": data["translations"]["en"]["article_body"] + "\n\nEditorial review completed."})
            save_form(admin)
            revision += 1
            edit_text(second, {"title": "This stale edit must not survive"})
            save_form(second, 409, "edit_conflict")
        finally:
            second.close()
        current = learner.context.request.get("/api/v1/topics/" + topic_id + "/?language=en").json()["data"]
        check(current["title"] == data["translations"]["en"]["title"] and current["article_body"].endswith("Editorial review completed."), "First Published edit must survive conflict")
        before = auth_app.content_admin_data("inspect", topic_id=topic_id)
        check(before["revision"] == revision and before["status"] == "published", "Conflict must not change Published revision")
        admin.goto(edit_path)
        edit_text(admin, {"title": "Incomplete edit must roll back", "article_body": ""})
        save_form(admin, 400, "incomplete_content")
        check(auth_app.content_admin_data("inspect", topic_id=topic_id) == before, "Incomplete Published edit must roll back atomically")
        check(learner.context.request.get("/api/v1/topics/" + topic_id + "/?language=en").json()["data"] == current, "Rejected edit must preserve article")

        # Change the live MC key while keeping Published structurally valid.
        # The existing attempt must still use its original private snapshot.
        admin.goto(admin_path("choice", extra_choice, "change"))
        admin.locator("#id_is_correct").check()
        save_form(admin)
        revision += 1
        change_status(admin, topic_id, revision, publish=False)
        revision += 1
        check(auth_app.content_admin_data("inspect", topic_id=topic_id)["revision"] == revision, "Unpublication must increment revision")
        for language in ("ru", "en"):
            for suffix in ("/", "/terms/"):
                response = learner.context.request.get("/api/v1/topics/" + topic_id + suffix + "?language=" + language)
                check(response.status == 404 and response.json()["error"]["code"] == "not_found", "Draft content must return the agreed 404")
            check(learner.context.request.get("/api/v1/attempts/" + pending + "/?language=" + language).json() == projections[language], "Public snapshot projection must remain unchanged")
        check(request_post(learner.context, "/api/v1/topics/" + topic_id + "/attempts/", {"language": "en"}).status == 404, "Draft must reject new attempts")
        check(request_post(learner.context, "/api/v1/topics/" + topic_id + "/read/", {}).status == 404, "Draft must reject new read marks")
        check(learner.context.request.get("/api/v1/progress/").json() == progress, "Unpublication must preserve the existing read mark")
        check(learner.context.request.get("/api/v1/attempts/").json() == history, "Unpublication must preserve completed history")
        learner.goto("/topics/" + topic_id)
        expect(learner.get_by_role("heading", name="Тема не найдена", exact=True)).to_be_visible()
        learner.goto("/attempts/" + pending)
        expect(learner.locator(".question-card")).to_be_visible()
        answer_demo(learner)
        learner.goto("/progress")
        expect(card(learner, topic_id).locator("dd")).to_have_text(["Прочитано", "Освоена", "2 из 2 (100%)"])
        expect(card(learner, topic_id).get_by_role("link")).to_have_count(0)

        # Staff status grants no learner ownership bypass.
        check(admin.context.request.get("/api/v1/progress/").json() == {"data": []}, "Content Admin must not see learner progress")
        check(admin.context.request.get("/api/v1/attempts/").json() == {"data": []}, "Content Admin must not see learner history")
        check(admin.context.request.get("/api/v1/attempts/" + pending + "/").status == 404, "Content Admin must not retrieve another attempt")
        check(request_post(admin.context, "/api/v1/attempts/" + pending + "/submit/", {"language": "ru", "answers": []}).status == 404, "Content Admin must not submit another attempt")
        learner_id = learner.context.request.get("/api/v1/auth/me/").json()["data"]["user_id"]
        for model, object_id, status in (("accounts/user", learner_id, 403), ("auth/group", editor["group_id"], 403),
                ("assessments/attempt", pending, 404), ("assessments/topicprogress", "1", 404)):
            path = "/admin/" + model + "/" + object_id + "/change/"
            check(admin.context.request.get(path).status == status, "Content Admin must not open real user data")
            check(request_post(admin.context, path, {}).status == status, "Content Admin must not mutate user data")
        other_context = auth_browser.new_context(base_url=auth_app.url, locale="ru-RU")
        try:
            other = other_context.new_page()
            signed_in(other)
            check(other_context.request.get("/api/v1/progress/").json() == {"data": []}, "Other learner must not see progress")
            check(other_context.request.get("/api/v1/attempts/" + pending + "/").status == 404, "Other learner must not retrieve an attempt")
        finally:
            other_context.close()
        print("CONTENT_ADMIN_ACCEPTANCE=PASS permissions, bilingual tree, atomic publication, revision, snapshot, ownership")
    finally:
        if topic_id is not None:
            check(auth_app.content_admin_data("cleanup", topic_id=topic_id) == {"cleanup": "PASS"}, "Owned demo cleanup failed")
