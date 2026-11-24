"""QIL-038: local Answer and a complete final submit over real HTTP/PostgreSQL."""
import json
from time import monotonic

import pytest
from playwright.sync_api import expect

from tests.e2e.test_auth_ui import check
from tests.e2e.test_learning_ui import signed_in
from tests.e2e.test_assessment_ui import begin, choose_correct, confirm_answers, result


pytestmark = pytest.mark.cross_browser
SIZES = [{"width": 1280, "height": 900}, {"width": 390, "height": 844}]


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_skip_return_local_answer_language_keyboard_and_finish(auth_page, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    signed_in(page)
    identifier = begin(page, learning_topics["first"])
    posts = []
    page.on("request", lambda request: posts.append(1) if request.method == "POST" and request.url.endswith("/submit/") else None)
    answer = page.get_by_role("button", name="Ответить", exact=True)
    finish = page.get_by_role("button", name="Завершить тест", exact=True)
    expect(page.locator(".question-navigation button")).to_have_text(["Предыдущий", "Ответить", "Следующий"])
    expect(answer).to_be_disabled()
    page.get_by_role("button", name="Следующий вопрос", exact=True).click()
    expect(finish).to_have_count(0)
    page.locator('.question-card input[type="radio"]').first.check()
    answer.focus()
    page.keyboard.press("Enter")
    expect(page.locator("#answer-confirmation")).to_have_text("Ответ подтверждён.")
    expect(answer).to_be_focused()
    expect(finish).to_have_count(0)
    page.get_by_role("button", name="Предыдущий вопрос", exact=True).click()
    expect(page.locator(".question-card h2")).to_be_focused()
    choices = page.locator('.question-card input[type="checkbox"]')
    choices.nth(0).focus()
    page.keyboard.press("Space")
    choices.nth(1).check()
    answer.click()
    expect(page.locator(".question-card legend")).to_have_text("Вопрос 1 из 2")
    page.get_by_role("button", name="Следующий вопрос", exact=True).click()
    expect(finish).to_be_enabled()
    language = page.get_by_role("radio", name="English", exact=True)
    language.focus()
    language.check()
    expect(language).to_be_focused()
    expect(page.locator("#answer-confirmation")).to_have_text("Ответ подтверждён.")
    expect(finish).to_be_enabled()
    page.go_back()
    expect(page.get_by_role("radio", name="Русский", exact=True)).to_be_checked()
    expect(finish).to_be_enabled()
    page.go_forward()
    expect(language).to_be_checked()
    page.get_by_role("button", name="Снять выбор", exact=True).click()
    expect(finish).to_have_count(0)
    expect(answer).to_be_disabled()
    page.locator('.question-card input[type="radio"]').first.check()
    expect(finish).to_have_count(0)
    answer.click()
    expect(finish).to_be_enabled()
    check(posts == [], "Answer, navigation and language must not POST submit")
    check(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Flow must fit desktop/mobile")
    finish.click()
    result(page)
    check(len(posts) == 1, "One explicit Finish must make one POST")
    payload = page.context.request.get(f"/api/v1/attempts/{identifier}/?language=en").json()["data"]
    check(set(payload["result"]) == {"correct_count", "total_count", "percentage"}, "Only public aggregates")


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_finish_double_click_and_reload_do_not_invent_confirmations(auth_page, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    signed_in(page)
    identifier = begin(page, learning_topics["first"])
    choose_correct(page)
    confirm_answers(page)
    page.reload()
    expect(page.locator(".question-card")).to_be_visible()
    expect(page.locator(".question-card input:checked")).to_have_count(0)
    expect(page.get_by_role("button", name="Завершить тест", exact=True)).to_have_count(0)
    choose_correct(page)
    confirm_answers(page)
    held = []
    page.route(f"**/api/v1/attempts/{identifier}/submit/", lambda route: held.append(route))
    page.get_by_role("button", name="Завершить тест", exact=True).evaluate("button => { button.click(); button.click(); }")
    expect(page.get_by_role("button", name="Отправляем ответы…", exact=True)).to_be_disabled()
    deadline = monotonic() + 5
    while not held and monotonic() < deadline:
        page.wait_for_timeout(20)
    check(len(held) == 1, "Double click must make one real submit")
    held[0].continue_()
    result(page)


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_real_incomplete_response_keeps_choices_for_explicit_finish(auth_page, auth_app, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    signed_in(page)
    topic_id = learning_topics["first"]
    identifier = begin(page, topic_id)
    choose_correct(page)
    confirm_answers(page)
    pattern = f"**/api/v1/attempts/{identifier}/submit/"
    def incomplete(route):
        payload = route.request.post_data_json
        payload["answers"][0]["choice_ids"] = []
        route.continue_(post_data=json.dumps(payload))
    page.route(pattern, incomplete)
    with page.expect_response(lambda response: response.url.endswith("/submit/")) as response:
        page.get_by_role("button", name="Завершить тест", exact=True).click()
    check(response.value.status == 400 and response.value.json()["error"]["code"] == "incomplete_answers", "Real backend completeness refusal")
    expect(page.get_by_role("alert")).to_contain_text("Выберите и подтвердите ответ на каждый вопрос")
    check(auth_app.learning_data("info", [topic_id])["submitted_count"] == 0, "Incomplete first submit must not save a result")
    expect(page.get_by_role("button", name="Завершить тест", exact=True)).to_be_enabled()
    page.unroute(pattern)
    page.get_by_role("button", name="Завершить тест", exact=True).click()
    result(page)
