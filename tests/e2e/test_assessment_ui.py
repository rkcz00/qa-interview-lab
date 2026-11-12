import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import expect
import pytest

from tests.e2e.test_auth_ui import check, fill, post, seed, LOGIN
from tests.e2e.test_learning_ui import signed_in, topic_page


def request_post(context, path, payload):
    bootstrap = context.request.get("/api/v1/auth/csrf/")
    check(bootstrap.status == 200, "CSRF bootstrap failed")
    token = bootstrap.json()["data"]["csrf_token"]
    response = context.request.post(path, data=payload, headers={"X-CSRFToken": token})
    token = None
    return response


def begin(page, topic_id, language="ru"):
    page.goto("/topics/" + topic_id + "/test" + ("?language=en" if language == "en" else ""))
    expect(page.get_by_role("button", name="Начать тест", exact=True)).to_be_enabled()
    page.get_by_role("button", name="Начать тест", exact=True).click()
    expect(page).to_have_url(re.compile(r"/attempts/[^/?]+(?:\?language=en)?$"))
    expect(page.locator(".question-card")).to_be_visible()
    return urlsplit(page.url).path.split("/")[-1]


def choose_correct(page, language="ru"):
    # Oracle is fixed by create_bilingual_topic: MC positions 10+20; SC position 10.
    page.locator(".question-card").get_by_role("checkbox", name=language + " choice 10", exact=True).check()
    page.locator(".question-card").get_by_role("checkbox", name=language + " choice 20", exact=True).check()
    page.get_by_role("button", name="Следующий вопрос", exact=True).click()
    page.locator(".question-card").get_by_role("radio", name=language + " choice 20", exact=True).check()
    page.locator(".question-card").get_by_role("radio", name=language + " choice 10", exact=True).check()
    check(page.locator(".question-card input:checked").count() == 1, "Single choice must contain only one selection")


def result(page, correct="2", total="2", percentage="100%"):
    expect(page.get_by_role("heading", name="Результат теста", exact=True)).to_be_visible()
    expect(page.locator(".result-summary dt")).to_have_text(["Верных ответов", "Всего вопросов", "Процент"])
    expect(page.locator(".result-summary dd")).to_have_text([correct, total, percentage])
    expect(page.locator(".question-card")).to_have_count(0)
    expect(page.get_by_role("button", name="Отправить тест", exact=True)).to_have_count(0)
    expect(page.get_by_role("group", name="Язык теста", exact=True)).to_have_count(0)


@pytest.mark.parametrize("article_language,test_language", [("ru", "ru"), ("ru", "en"), ("en", "ru"), ("en", "en")])
def test_article_and_test_languages_are_independent(auth_page, auth_app, learning_topics, article_language, test_language):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    topic_page(page, topic_id, article_language)
    page.get_by_role("link", name="Пройти тест", exact=True).click()
    expect(page.get_by_role("radio", name="Русский", exact=True)).to_be_checked()
    if test_language == "en":
        page.get_by_role("radio", name="English", exact=True).check()
    page.get_by_role("button", name="Начать тест", exact=True).click()
    expect(page.locator(".question-card h2")).to_have_text(test_language + " question 10")
    check(page.locator("html").get_attribute("lang") == "ru", "Test language must not change the UI language")
    page.get_by_role("link", name="К статье", exact=True).click()
    expect(page.locator(".article-body")).to_have_attribute("lang", article_language)
    page.go_back()
    expect(page.locator(".question-card h2")).to_have_text(test_language + " question 10")
    check(auth_app.learning_data("info", [topic_id])["attempt_count"] == 1, "Back must restore the attempt without creating a new one")


def test_start_double_click_and_get_restore_create_only_one_attempt(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    page.goto("/topics/" + topic_id + "/test")
    held = []
    page.route("**/api/v1/topics/" + topic_id + "/attempts/", lambda route: held.append(route))
    page.get_by_role("button", name="Начать тест", exact=True).click()
    expect(page.get_by_role("button", name="Начинаем тест…", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Начинаем тест…", exact=True).evaluate("button => button.click()")
    page.wait_for_timeout(100)
    check(len(held) == 1, "Double start must not create two requests")
    check(bool(held[0].request.headers.get("x-csrftoken")), "Start must use CSRF")
    held[0].continue_()
    expect(page.locator(".question-card")).to_be_visible()
    page.reload()
    expect(page.locator(".question-card")).to_be_visible()
    check(auth_app.learning_data("info", [topic_id])["attempt_count"] == 1, "Reload must not start another attempt")


def test_language_switch_back_forward_preserves_answers_and_question_index(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    begin(page, learning_topics["first"])
    page.locator(".question-card").get_by_role("checkbox", name="ru choice 10", exact=True).check()
    page.get_by_role("button", name="Следующий вопрос", exact=True).click()
    page.locator(".question-card").get_by_role("radio", name="ru choice 20", exact=True).check()
    page.get_by_role("radio", name="English", exact=True).check()
    expect(page.locator(".question-card legend")).to_have_text("Вопрос 2 из 2")
    expect(page.locator(".question-card").get_by_role("radio", name="en choice 20", exact=True)).to_be_checked()
    page.go_back()
    expect(page.locator(".question-card").get_by_role("radio", name="ru choice 20", exact=True)).to_be_checked()
    page.go_forward()
    expect(page.locator(".question-card").get_by_role("radio", name="en choice 20", exact=True)).to_be_checked()
    page.get_by_role("button", name="Предыдущий вопрос", exact=True).click()
    expect(page.locator(".question-card").get_by_role("checkbox", name="en choice 10", exact=True)).to_be_checked()


def test_submit_only_aggregates_idempotent_repeat_keyboard_and_layout(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    attempt_id = begin(page, topic_id)
    # Keyboard selection uses native checkboxes; moving forward retains it.
    first = page.locator(".question-card").get_by_role("checkbox", name="ru choice 10", exact=True)
    first.focus()
    page.keyboard.press("Space")
    expect(first).to_be_checked()
    choose_correct(page)
    requests = []

    def capture(route):
        requests.append(route.request.post_data_json)
        check(bool(route.request.headers.get("x-csrftoken")), "Submit must use CSRF")
        route.continue_()

    page.route("**/api/v1/attempts/" + attempt_id + "/submit/", capture)
    page.get_by_role("button", name="Отправить тест", exact=True).click()
    result(page)
    check(len(requests) == 1, "One explicit UI submit is expected")
    check(set(requests[0]) == {"language", "answers"}, "Submit payload must contain only agreed fields")
    history = page.context.request.get("/api/v1/attempts/").json()
    repeated = request_post(page.context, "/api/v1/attempts/" + attempt_id + "/submit/", requests[0])
    check(repeated.status == 200, "Equivalent repeat must return HTTP 200")
    check(page.context.request.get("/api/v1/attempts/").json() == history, "Equivalent repeat must preserve the same single history entry")
    check(auth_app.learning_data("info", [topic_id])["submitted_count"] == 1, "Only one result may be stored")
    allowed = {"attempt_id", "topic_id", "topic_title", "status", "submitted_language", "submitted_at", "result"}
    check(set(repeated.json()["data"]) == allowed, "Submitted response must not expose questions or internal snapshot")
    check(set(repeated.json()["data"]["result"]) == {"correct_count", "total_count", "percentage"}, "Result may contain only three aggregates")
    for size, name in (({"width": 1280, "height": 900}, "desktop"), ({"width": 375, "height": 812}, "mobile")):
        page.set_viewport_size(size)
        check(page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Result must fit the viewport")
        visual = os.environ.get("QIL_ASSESSMENT_VISUAL_DIR")
        if visual:
            directory = Path(visual).resolve()
            root = Path(__file__).resolve().parents[2]
            check(directory.parent == root / ".cache" and directory.name.startswith("qil020-"), "Unsafe visual target")
            directory.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(directory / (name + ".png")), full_page=True)
    page.reload()
    result(page)


def test_lost_saved_submit_response_is_confirmed_by_get_without_another_post(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    attempt_id = begin(page, topic_id)
    choose_correct(page)
    writes = []

    def response_lost(route):
        writes.append(1)
        response = route.fetch()
        check(response.status == 200, "The real backend submit must complete before disconnect")
        route.abort("failed")

    page.route("**/api/v1/attempts/" + attempt_id + "/submit/", response_lost)
    page.get_by_role("button", name="Отправить тест", exact=True).click()
    result(page)
    check(len(writes) == 1, "A lost response must not automatically replay POST")
    check(auth_app.learning_data("info", [topic_id])["submitted_count"] == 1, "Saved result must remain unique")


def test_network_failure_freezes_payload_and_explicit_retry_uses_the_same_answers(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    attempt_id = begin(page, topic_id)
    choose_correct(page)
    writes = []

    def disconnected_once(route):
        writes.append(route.request.post_data_json)
        if len(writes) == 1: route.abort("failed")
        else: route.continue_()

    page.route("**/api/v1/attempts/" + attempt_id + "/submit/", disconnected_once)
    page.get_by_role("button", name="Отправить тест", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Результат пока неизвестен.")
    expect(page.locator(".question-card")).to_have_count(0)
    page.get_by_role("button", name="Повторить ту же отправку", exact=True).click()
    result(page)
    check(len(writes) == 2 and writes[0] == writes[1], "Explicit retry must send exactly the frozen payload")
    check(auth_app.learning_data("info", [topic_id])["submitted_count"] == 1, "Retry must not duplicate history")


def test_submit_timeout_never_displays_a_guessed_grade_or_replays_automatically(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    attempt_id = begin(page, learning_topics["first"])
    page.evaluate("() => { const original = AbortSignal.timeout.bind(AbortSignal); AbortSignal.timeout = () => original(500) }")
    held = []
    page.route("**/api/v1/attempts/" + attempt_id + "/submit/", lambda route: held.append(route))
    page.get_by_role("button", name="Отправить тест", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Результат пока неизвестен.")
    expect(page.locator(".result-summary")).to_have_count(0)
    check(len(held) == 1, "Timeout must not repeat POST")
    held[0].abort()


@pytest.mark.parametrize("failure_kind", ["validation", "csrf"])
def test_real_validation_and_csrf_refusal_allow_a_corrected_explicit_submit(auth_page, auth_app, learning_topics, failure_kind):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    attempt_id = begin(page, topic_id)
    choose_correct(page)
    pattern = "**/api/v1/attempts/" + attempt_id + "/submit/"

    def invalid_request(route):
        if failure_kind == "csrf":
            route.continue_(headers={key: value for key, value in route.request.headers.items() if key.lower() != "x-csrftoken"})
        else:
            payload = route.request.post_data_json
            payload["answers"] = [{"question_id": "unknown", "choice_ids": []}]
            route.continue_(post_data=json.dumps(payload))

    page.route(pattern, invalid_request)
    with page.expect_response(lambda response: response.url.endswith("/submit/")) as response:
        page.get_by_role("button", name="Отправить тест", exact=True).click()
    wanted_status, wanted_code = (403, "csrf_failed") if failure_kind == "csrf" else (400, "validation_error")
    check(response.value.status == wanted_status and response.value.json()["error"]["code"] == wanted_code, "Expected the documented real backend rejection")
    expect(page.get_by_role("alert")).to_contain_text("Не удалось подтвердить запрос." if failure_kind == "csrf" else "Ответы не приняты.")
    check(auth_app.learning_data("info", [topic_id])["submitted_count"] == 0, "Rejected request must not store a result")
    page.unroute(pattern)
    page.get_by_role("button", name="Отправить тест", exact=True).click()
    result(page)


def test_conflict_uses_the_other_submitted_result_without_overwriting_it(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    attempt_id = begin(page, topic_id)
    choose_correct(page)
    check(request_post(page.context, "/api/v1/attempts/" + attempt_id + "/submit/", {"language": "ru", "answers": []}).status == 200,
        "Concurrent tab's synthetic submission failed")
    with page.expect_response(lambda response: response.url.endswith("/submit/")) as response:
        page.get_by_role("button", name="Отправить тест", exact=True).click()
    check(response.value.status == 409 and response.value.json()["error"]["code"] == "attempt_already_submitted", "Changed completed payload must conflict")
    result(page, "0", "2", "0%")
    expect(page.get_by_role("status")).to_contain_text("Эта попытка уже отправлена.")
    check(auth_app.learning_data("info", [topic_id])["submitted_count"] == 1, "Conflict must preserve the single saved result")


def test_foreign_attempt_and_missing_attempt_have_the_same_safe_404(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    attempt_id = begin(page, learning_topics["first"])
    check(post(page.context, "/api/v1/auth/logout/").status == 204, "Synthetic logout failed")
    signed_in(page)
    for identifier in (attempt_id, "0"):
        with page.expect_response(lambda response: "/api/v1/attempts/" + identifier + "/?" in response.url) as response:
            page.goto("/attempts/" + identifier)
        check(response.value.status == 404, "Foreign/missing attempt must use real backend 404")
        expect(page.get_by_role("heading", name="Тест недоступен", exact=True)).to_be_visible()
        expect(page.locator(".question-card,.result-summary")).to_have_count(0)


def test_guest_start_returns_after_login_without_redirect_parameters(auth_page, learning_topics):
    page = auth_page
    email, password = seed(page.context)
    target = "/topics/" + learning_topics["first"] + "/test?language=en"
    page.goto(target)
    expect(page).to_have_url(re.compile(r"/login$"))
    fill(page, email, password)
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page).to_have_url(re.compile(re.escape(target) + r"$"))
    expect(page.get_by_role("radio", name="English", exact=True)).to_be_checked()
    expect(page.get_by_role("button", name="Начать тест", exact=True)).to_be_enabled()


def test_draft_start_and_unpublication_before_start_do_not_create_attempts(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    page.goto("/topics/" + learning_topics["draft"] + "/test")
    expect(page.get_by_role("heading", name="Тест недоступен", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Начать тест", exact=True)).to_have_count(0)
    page.goto("/topics/" + topic_id + "/test")
    expect(page.get_by_role("button", name="Начать тест", exact=True)).to_be_enabled()
    auth_app.learning_data("draft", [topic_id])
    page.get_by_role("button", name="Начать тест", exact=True).click()
    expect(page.get_by_role("heading", name="Тест недоступен", exact=True)).to_be_visible()
    check(auth_app.learning_data("info", [topic_id])["attempt_count"] == 0, "Unpublished topic must not get an attempt")


def test_started_attempt_finishes_from_snapshot_after_unpublication(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    begin(page, topic_id)
    auth_app.learning_data("draft", [topic_id])
    page.reload()
    expect(page.locator(".question-card h2")).to_have_text("ru question 10")
    choose_correct(page)
    page.get_by_role("button", name="Отправить тест", exact=True).click()
    result(page)


def test_lost_start_response_requires_explicit_new_attempt_and_does_not_create_history(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    page.goto("/topics/" + topic_id + "/test")
    writes = []

    def lost_once(route):
        writes.append(1)
        if len(writes) == 1:
            response = route.fetch()
            check(response.status == 201, "Real start must commit before losing the response")
            route.abort("failed")
        else:
            route.continue_()

    page.route("**/api/v1/topics/" + topic_id + "/attempts/", lost_once)
    page.get_by_role("button", name="Начать тест", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Начало теста не подтверждено.")
    check(len(writes) == 1, "Lost start response must not repeat POST automatically")
    check(auth_app.learning_data("info", [topic_id])["attempt_count"] == 1, "First unconfirmed start must remain one attempt")
    check(page.context.request.get("/api/v1/attempts/").json() == {"data": []}, "Unsubmitted attempts must not appear in result history")
    page.get_by_role("button", name="Начать новую попытку", exact=True).click()
    expect(page.locator(".question-card")).to_be_visible()
    check(len(writes) == 2 and auth_app.learning_data("info", [topic_id])["attempt_count"] == 2,
        "A second attempt requires the explicit new-attempt action")


def test_conflict_with_unavailable_result_get_never_offers_another_submit(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    attempt_id = begin(page, learning_topics["first"])
    choose_correct(page)
    check(request_post(page.context, "/api/v1/attempts/" + attempt_id + "/submit/", {"language": "ru", "answers": []}).status == 200,
        "Other tab's real submission failed")
    pattern = "**/api/v1/attempts/" + attempt_id + "/?*"
    page.route(pattern, lambda route: route.abort("failed"))
    page.get_by_role("button", name="Отправить тест", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Попытка уже отправлена, но сохранённый результат пока не удалось получить.")
    expect(page.locator(".question-card,.result-summary")).to_have_count(0)
    expect(page.get_by_role("button", name="Повторить ту же отправку", exact=True)).to_have_count(0)
    page.unroute(pattern)
    page.get_by_role("button", name="Проверить результат", exact=True).click()
    result(page, "0", "2", "0%")
