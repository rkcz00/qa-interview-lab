"""Whole learner journeys through the built SPA and real isolated Django/PostgreSQL."""

from copy import deepcopy
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import expect
import pytest

from tests.e2e.test_auth_ui import check, fill, form, identity, post, LOGIN, ME, REGISTER
from tests.e2e.test_learning_ui import signed_in
from tests.e2e.test_assessment_ui import begin, choose_correct, request_post, result
from tests.e2e.test_progress_ui import card, complete, open_progress


SUBMITTED_FIELDS = {"attempt_id", "topic_id", "topic_title", "status", "submitted_language", "submitted_at", "result"}
RESULT_FIELDS = {"correct_count", "total_count", "percentage"}


def public_attempt(data):
    """Assert positive allowlists without dumping response values on failure."""
    if data.get("status") == "submitted":
        check(set(data) == SUBMITTED_FIELDS, "Submitted attempt contains unexpected fields")
        check(set(data["result"]) == RESULT_FIELDS, "Result must have exactly three public aggregates")
    else:
        check(set(data) == {"attempt_id", "topic_id", "status", "language", "questions"}, "Pending attempt contains unexpected fields")
        for question in data["questions"]:
            check(set(question) == {"question_id", "position", "question_type", "text", "choices"}, "Question contains unexpected fields")
            for choice in question["choices"]:
                check(set(choice) == {"choice_id", "position", "text"}, "Choice contains unexpected fields")


def fit(page):
    check(page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Learner page overflows the viewport")


def login_ui(page, email, password):
    fill(page, email, password)
    page.get_by_label("Пароль", exact=True).press("Enter")
    expect(page).to_have_url(re.compile(r"/session$"))
    expect(page.get_by_role("button", name="Выйти", exact=True)).to_be_visible()


@pytest.mark.parametrize("article_language,test_language,width", [
    ("ru", "ru", 1280), ("ru", "en", 390), ("en", "ru", 390), ("en", "en", 1280),
], ids=["ru-ru-desktop", "ru-en-mobile", "en-ru-mobile", "en-en-desktop"])
def test_mvp_learner_journey(auth_page, auth_app, learning_topics, article_language, test_language, width):
    page = auth_page
    page.set_viewport_size({"width": width, "height": 900 if width > 600 else 844})
    console = []
    page.on("console", lambda message: console.append(message.text))
    email, password = identity()
    topic_id = learning_topics["first"]

    form(page, "/register")
    fit(page)
    fill(page, email.upper(), password)
    with page.expect_response(lambda response: response.url.endswith(REGISTER)) as registered:
        page.get_by_role("button", name="Зарегистрироваться", exact=True).click()
    check(registered.value.status == 201, "Registration did not create the synthetic learner")
    check(set(registered.value.json()["data"]) == {"user_id", "email"}, "Registration exposed unexpected account fields")
    expect(page).to_have_url(re.compile(r"/login$"))
    check(page.context.request.get(ME).status == 403, "Registration must not automatically authenticate")
    login_ui(page, email, password)
    page.reload()
    expect(page.locator(".session-email")).to_have_text(email)

    page.get_by_role("link", name="Темы подготовки", exact=True).click()
    expect(page.locator(".topic-list").get_by_role("link")).to_have_text(["Основы тестирования", "Автоматизация"])
    page.get_by_role("link", name="Основы тестирования", exact=True).click()
    expect(page.locator(".glossary dt")).to_have_text(["Риск", "Оракул", "Качество"])
    page.get_by_role("radio", name="English", exact=True).check()
    expect(page.locator(".article-body")).to_have_attribute("lang", "en")
    expect(page.locator(".glossary dt")).to_have_text(["Risk", "Oracle", "Quality"])
    check(page.context.request.get("/api/v1/progress/").json() == {"data": []}, "Reading or glossary must not mark the article")
    if article_language == "ru":
        page.get_by_role("radio", name="Русский", exact=True).check()
    page.get_by_role("button", name="Отметить «Прочитано»", exact=True).click()
    expect(page.get_by_role("button", name="Прочитано", exact=True)).to_be_disabled()
    before = page.context.request.get("/api/v1/progress/").json()["data"]
    check(len(before) == 1 and before[0]["article_read_at"] is not None, "One explicit read mark is required")
    other = "English" if article_language == "ru" else "Русский"
    original = "Русский" if article_language == "ru" else "English"
    page.get_by_role("radio", name=other, exact=True).check()
    expect(page.get_by_role("button", name="Прочитано", exact=True)).to_be_disabled()
    page.get_by_role("radio", name=original, exact=True).check()
    expect(page.locator(".article-body")).to_have_attribute("lang", article_language)
    check(page.context.request.get("/api/v1/progress/").json()["data"] == before, "RU/EN must share the first read mark")
    fit(page)

    page.get_by_role("link", name="Пройти тест", exact=True).click()
    expect(page.get_by_role("radio", name="Русский", exact=True)).to_be_checked()
    if test_language == "en":
        page.get_by_role("radio", name="English", exact=True).check()
    with page.expect_response(lambda response: response.url.endswith("/topics/" + topic_id + "/attempts/")) as started:
        page.get_by_role("button", name="Начать тест", exact=True).click()
    check(started.value.status == 201, "Start must create exactly one real attempt")
    public_attempt(started.value.json()["data"])
    expect(page.locator(".question-card")).to_be_visible()
    attempt_id = urlsplit(page.url).path.split("/")[-1]
    choose_correct(page, test_language)
    switched = "English" if test_language == "ru" else "Русский"
    page.get_by_role("radio", name=switched, exact=True).check()
    expect(page.locator(".question-card h2")).to_have_text(("en" if test_language == "ru" else "ru") + " question 20")
    expect(page.locator(".question-card legend")).to_have_text("Вопрос 2 из 2")
    check(page.locator(".question-card input:checked").count() == 1, "Single-choice selection was lost after language switch")
    page.get_by_role("radio", name="Русский" if test_language == "ru" else "English", exact=True).check()
    expect(page.locator(".question-card h2")).to_have_text(test_language + " question 20")
    page.get_by_role("button", name="Предыдущий вопрос", exact=True).click()
    check(page.locator(".question-card input:checked").count() == 2, "Multiple-choice selections must survive language switch")
    page.locator('.question-card input[type="checkbox"]:checked').first.focus()
    page.keyboard.press("Space")
    check(page.locator(".question-card input:checked").count() == 1, "Keyboard must toggle the checkbox")
    page.keyboard.press("Space")
    check(page.locator(".question-card input:checked").count() == 2, "Keyboard must restore the checkbox")
    page.get_by_role("button", name="Следующий вопрос", exact=True).click()
    page.locator('.question-card input[type="radio"]:checked').focus()
    page.keyboard.press("Space")
    check(page.locator(".question-card input:checked").count() == 1, "Radio must retain a single selection")
    fit(page)
    expected_article = "/topics/" + topic_id + ("?language=en" if article_language == "en" else "")
    check(page.get_by_role("link", name="К статье", exact=True).get_attribute("href") == expected_article, "Test language must not change the remembered material language")

    payloads = []
    submit_path = "/api/v1/attempts/" + attempt_id + "/submit/"
    page.on("request", lambda request: payloads.append(request.post_data_json) if request.url.endswith(submit_path) and request.method == "POST" else None)
    with page.expect_response(lambda response: response.url.endswith(submit_path)) as submitted:
        page.get_by_role("button", name="Отправить тест", exact=True).click()
    check(submitted.value.status == 200 and len(payloads) == 1, "UI must submit once through the real backend")
    saved = submitted.value.json()
    public_attempt(saved["data"])
    result(page)
    fit(page)
    equivalent = deepcopy(payloads[0])
    equivalent["answers"].reverse()
    for answer in equivalent["answers"]:
        answer["choice_ids"].reverse()
    repeated = request_post(page.context, submit_path, equivalent)
    check(repeated.status == 200 and repeated.json() == saved, "Normalized repeat must preserve the same result and timestamp")
    conflict = request_post(page.context, submit_path, {"language": test_language, "answers": []})
    check(conflict.status == 409 and conflict.json()["error"]["code"] == "attempt_already_submitted", "Changed completed payload must conflict")
    history = page.context.request.get("/api/v1/attempts/").json()["data"]
    check(len(history) == 1 and history[0] == saved["data"], "Repeat or conflict must not change or duplicate history")

    page.get_by_role("link", name="Мой прогресс", exact=True).click()
    expect(card(page, topic_id).locator("dd")).to_have_text(["Прочитано", "Освоена", "2 из 2 (100%)"])
    expect(page.locator(".attempt-history-list > li")).to_have_count(1)
    expect(page.locator(".attempt-history-list dd").nth(1)).to_have_text("Русский" if test_language == "ru" else "English")
    page.get_by_role("link", name="Открыть сохранённый результат", exact=True).click()
    result(page)
    page.go_back()
    expect(card(page, topic_id)).to_be_visible()
    page.reload()
    expect(card(page, topic_id).locator("dd")).to_have_text(["Прочитано", "Освоена", "2 из 2 (100%)"])

    page.get_by_role("link", name="Мой аккаунт", exact=True).click()
    page.get_by_role("button", name="Выйти", exact=True).click()
    expect(page).to_have_url(re.compile(r"/login$"))
    check(page.context.request.get(ME).status == 403, "Logout must invalidate the learner session")
    login_ui(page, email, password)
    page.get_by_role("link", name="Мой прогресс", exact=True).click()
    expect(card(page, topic_id).locator("dd")).to_have_text(["Прочитано", "Освоена", "2 из 2 (100%)"])
    check(page.context.request.get("/api/v1/attempts/").json()["data"] == history, "History must survive a new session")
    check(auth_app.learning_data("info", [topic_id]) == {"read_count": 1, "attempt_count": 1, "submitted_count": 1}, "Journey must not create duplicate data")
    fit(page)
    body = page.locator("body").inner_text()
    private_values = [password, *[cookie["value"] for cookie in page.context.cookies() if cookie["name"] in {"csrftoken", "sessionid"}]]
    check(not any(value in body or any(value in message for message in console) for value in private_values), "Credentials must not appear in UI or console")
    check(page.evaluate("localStorage.length === 0 && sessionStorage.length === 0"), "Learner journey must not persist secrets")

    visual = os.environ.get("QIL_MVP_VISUAL_DIR")
    if visual:
        directory = Path(visual).resolve()
        check(directory.parent == Path(__file__).resolve().parents[2] / ".cache" and directory.name.startswith("qil022-"), "Unsafe visual directory")
        directory.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(directory / (article_language + "-" + test_language + ".png")), full_page=True)


def test_mvp_unpublish_edit_snapshot_and_second_user_isolation(auth_page, auth_app, auth_browser, learning_topics):
    page = auth_page
    email, password = signed_in(page)
    topic_id = learning_topics["first"]
    check(request_post(page.context, "/api/v1/topics/" + topic_id + "/read/", {}).status == 200, "Read mark failed")
    complete(page.context, topic_id, "en")
    saved_progress = page.context.request.get("/api/v1/progress/").json()
    pending_id = begin(page, topic_id, "ru")
    snapshots = {}
    for language in ("ru", "en"):
        response = page.context.request.get("/api/v1/attempts/" + pending_id + "/?language=" + language)
        check(response.status == 200, "Owned pending attempt must be readable")
        public_attempt(response.json()["data"])
        snapshots[language] = response.json()
    # These are public question projections only, never the server snapshot or keys.
    auth_app.learning_data("draft", [topic_id])
    auth_app.learning_data("revise_draft", [topic_id])
    for language in ("ru", "en"):
        for suffix in ("/", "/terms/"):
            check(page.context.request.get("/api/v1/topics/" + topic_id + suffix + "?language=" + language).status == 404, "Draft content must be hidden")
        response = page.context.request.get("/api/v1/attempts/" + pending_id + "/?language=" + language)
        check(response.status == 200 and response.json() == snapshots[language], "Pending public questions must retain both original translations after edits")
    check(request_post(page.context, "/api/v1/topics/" + topic_id + "/attempts/", {"language": "en"}).status == 404, "Draft must reject new attempts")
    check(request_post(page.context, "/api/v1/topics/" + topic_id + "/read/", {}).status == 404, "Draft must reject new read access")
    check(all(topic["topic_id"] != topic_id for topic in page.context.request.get("/api/v1/topics/?language=ru").json()["data"]), "Unpublished topic must disappear from catalog")
    check(page.context.request.get("/api/v1/progress/").json() == saved_progress, "Unpublication or editing must not recalculate existing progress")

    other_context = auth_browser.new_context(base_url=auth_app.url, locale="ru-RU")
    try:
        other = other_context.new_page()
        other.set_default_timeout(8_000)
        signed_in(other)
        check(other_context.request.get("/api/v1/progress/").json() == {"data": []}, "Second user must not see another progress")
        check(other_context.request.get("/api/v1/attempts/").json() == {"data": []}, "Second user must not see another history")
        check(other_context.request.get("/api/v1/attempts/" + pending_id + "/").status == 404, "Second user must not retrieve the pending attempt")
        check(request_post(other_context, "/api/v1/attempts/" + pending_id + "/submit/", {"language": "ru", "answers": []}).status == 404, "Second user must not submit another attempt")
        open_progress(other)
        expect(card(other, topic_id)).to_have_count(0)
        expect(other.locator(".attempt-history-list")).to_have_count(0)
    finally:
        other_context.close()

    page.reload()
    expect(page.locator(".question-card h2")).to_have_text("ru question 10")
    choose_correct(page)
    page.get_by_role("button", name="Отправить тест", exact=True).click()
    result(page)
    page.get_by_role("link", name="Мой прогресс", exact=True).click()
    expect(card(page, topic_id).locator("dd")).to_have_text(["Прочитано", "Освоена", "2 из 2 (100%)"])
    expect(card(page, topic_id).get_by_role("link")).to_have_count(0)
    expect(page.locator(".attempt-history-list > li")).to_have_count(2)
    check(page.context.request.get("/api/v1/progress/").json() == saved_progress, "Completing the old attempt must preserve the same read mark and mastery")
    page.get_by_role("link", name="Мой аккаунт", exact=True).click()
    page.get_by_role("button", name="Выйти", exact=True).click()
    expect(page).to_have_url(re.compile(r"/login$"))
    login_ui(page, email, password)
    page.get_by_role("link", name="Мой прогресс", exact=True).click()
    expect(card(page, topic_id).locator("dd")).to_have_text(["Прочитано", "Освоена", "2 из 2 (100%)"])
    expect(page.locator(".attempt-history-list > li")).to_have_count(2)
