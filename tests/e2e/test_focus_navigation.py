"""QIL-026: focus and shared learner navigation against real HTTP/PostgreSQL."""

import json
import os
from pathlib import Path
import re

import pytest
from playwright.sync_api import expect

from tests.e2e.test_auth_ui import check, fill, identity, REGISTER, ME, form
from tests.e2e.test_learning_ui import signed_in, topic_page
from tests.e2e.test_assessment_ui import result


SIZES = [{"width": 1280, "height": 900}, {"width": 390, "height": 844}]


def visual(page, name, size):
    target = os.environ.get("QIL_FOCUS_VISUAL_DIR")
    if not target:
        return
    directory = Path(target).resolve()
    root = Path(__file__).resolve().parents[2]
    check(directory.parent == root / ".cache" and directory.name.startswith("qil026-"), "Unsafe visual output directory")
    directory.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(directory / (name + "-" + str(size["width"]) + ".png")), full_page=True)


def active_section(page, target):
    target = "/" if target == "/topics" else target
    nav = page.get_by_role("navigation", name="Основная навигация", exact=True)
    expect(nav.locator("a[aria-current]")).to_have_count(1)
    expect(nav.locator("a[aria-current]")).to_have_attribute("href", target)
    expect(nav.get_by_role("link", name="Темы подготовки", exact=True)).to_have_attribute("href", "/")
    expect(nav.get_by_role("link", name="Мой прогресс", exact=True)).to_have_attribute("href", "/progress")
    expect(nav.get_by_role("link", name="Мой аккаунт", exact=True)).to_have_attribute("href", "/session")
    check(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Learner shell must fit the viewport")


def heading_counter(page):
    page.add_init_script("""
        window.qilHeadingFocusCount = 0;
        document.addEventListener('focusin', event => {
            if (event.target.tagName === 'H1') window.qilHeadingFocusCount++;
        });
    """)


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_material_and_start_selector_keep_focus_in_both_directions(auth_page, auth_app, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    signed_in(page)
    heading_counter(page)
    topic_id = learning_topics["first"]
    auth_app.learning_data("long_article", [topic_id])
    topic_page(page, topic_id)
    expect(page.get_by_role("heading", name="Основы тестирования", exact=True)).to_be_focused()
    active_section(page, "/topics")
    ru = page.get_by_role("radio", name="Русский", exact=True)
    en = page.get_by_role("radio", name="English", exact=True)
    ru.focus()
    page.keyboard.press("ArrowRight")
    expect(page.locator(".article-body")).to_have_attribute("lang", "en")
    expect(en).to_be_focused()
    page.keyboard.press("ArrowLeft")
    expect(page.locator(".article-body")).to_have_attribute("lang", "ru")
    expect(ru).to_be_focused()
    page.go_back()
    expect(page.locator(".article-body")).to_have_attribute("lang", "en")
    page.go_forward()
    expect(page.locator(".article-body")).to_have_attribute("lang", "ru")
    check(page.evaluate("window.qilHeadingFocusCount === 1"), "Translation and history must not focus the article heading again")
    check(auth_app.learning_data("info", [topic_id])["read_count"] == 0, "Language changes must not write progress")
    en.check()
    expect(page.locator(".article-body")).to_have_attribute("lang", "en")
    page.evaluate("window.qilHeadingFocusCount = 0")
    page.get_by_role("link", name="Пройти тест", exact=True).click()
    expect(page.get_by_role("heading", name="Начало теста", exact=True)).to_be_focused()
    expect(ru).to_be_checked()
    ru.focus()
    page.keyboard.press("ArrowRight")
    expect(page.get_by_role("heading", name="Testing foundations", exact=True)).to_be_visible()
    expect(en).to_be_focused()
    page.keyboard.press("ArrowLeft")
    expect(page.get_by_role("heading", name="Основы тестирования", exact=True)).to_be_visible()
    expect(ru).to_be_focused()
    check(page.evaluate("window.qilHeadingFocusCount === 1"), "Start language changes must not focus its heading again")
    check(auth_app.learning_data("info", [topic_id])["attempt_count"] == 0, "Choosing a test language must not create an attempt")
    visual(page, "language-focus", size)


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_attempt_keyboard_answers_result_context_navigation_and_logout(auth_page, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    signed_in(page)
    topic_id = learning_topics["first"]
    topic_page(page, topic_id, "en")
    page.get_by_role("link", name="Пройти тест", exact=True).click()
    expect(page.get_by_role("radio", name="Русский", exact=True)).to_be_checked()
    page.get_by_role("button", name="Начать тест", exact=True).click()
    expect(page.get_by_role("heading", name="Тестирование", exact=True)).to_be_focused()
    active_section(page, "/topics")
    first = page.locator(".question-card").get_by_role("checkbox", name="ru choice 10", exact=True)
    first.focus()
    page.keyboard.press("Space")
    page.locator(".question-card").get_by_role("checkbox", name="ru choice 20", exact=True).check()
    page.get_by_role("button", name="Следующий вопрос", exact=True).click()
    expect(page.locator(".question-card h2")).to_be_focused()
    chosen = page.locator(".question-card").get_by_role("radio", name="ru choice 10", exact=True)
    chosen.focus()
    page.keyboard.press("Space")
    ru = page.get_by_role("radio", name="Русский", exact=True)
    en = page.get_by_role("radio", name="English", exact=True)
    ru.focus()
    page.keyboard.press("ArrowRight")
    expect(page.locator(".question-card h2")).to_have_text("en question 20")
    expect(en).to_be_focused()
    expect(page.locator(".question-card").get_by_role("radio", name="en choice 10", exact=True)).to_be_checked()
    page.keyboard.press("ArrowLeft")
    expect(page.locator(".question-card h2")).to_have_text("ru question 20")
    expect(ru).to_be_focused()
    expect(chosen).to_be_checked()
    page.go_back()
    expect(page.locator(".question-card h2")).to_have_text("en question 20")
    page.go_forward()
    expect(chosen).to_be_checked()
    page.get_by_role("button", name="Предыдущий вопрос", exact=True).click()
    expect(first).to_be_checked()
    expect(page.locator(".question-card").get_by_role("checkbox", name="ru choice 20", exact=True)).to_be_checked()
    page.get_by_role("button", name="Следующий вопрос", exact=True).click()
    page.get_by_role("button", name="Отправить тест", exact=True).focus()
    page.keyboard.press("Enter")
    result(page)
    expect(page.get_by_role("heading", name="Результат теста", exact=True)).to_be_focused()
    expect(page.locator(".result-topic")).to_have_text("Основы тестирования")
    expect(page.locator(".result-topic")).to_have_attribute("lang", "ru")
    article = page.get_by_role("link", name="К статье", exact=True)
    expect(article).to_have_attribute("href", "/topics/" + topic_id + "?language=en")
    visual(page, "result-navigation", size)
    topics_link = page.get_by_role("navigation", name="Основная навигация", exact=True).get_by_role("link", name="Темы подготовки", exact=True)
    topics_link.focus()
    page.go_back()
    result(page)
    expect(topics_link).to_be_focused()
    page.go_forward()
    result(page)
    expect(topics_link).to_be_focused()
    page.reload()
    result(page)
    expect(page.locator(".result-topic")).to_have_text("Основы тестирования")
    saved_result_url = page.url
    page.get_by_role("link", name="Посмотреть прогресс", exact=True).click()
    expect(page.get_by_role("heading", name="Мой прогресс", exact=True)).to_be_focused()
    active_section(page, "/progress")
    expect(page.locator("main .overall-progress")).to_be_visible()
    expect(page.locator(".attempt-history-list")).to_have_count(0)
    page.goto(saved_result_url)
    result(page)
    active_section(page, "/topics")
    page.get_by_role("link", name="К статье", exact=True).click()
    expect(page.locator(".article-body")).to_have_attribute("lang", "ru")
    page.go_back()
    result(page)
    page.go_forward()
    expect(page.locator(".article-body")).to_be_visible()
    page.get_by_role("navigation", name="Основная навигация", exact=True).get_by_role("link", name="Мой аккаунт", exact=True).click()
    active_section(page, "/session")
    expect(page.get_by_role("heading", name="Текущая сессия", exact=True)).to_be_focused()
    page.get_by_role("button", name="Выйти", exact=True).click()
    expect(page).to_have_url(re.compile(r"/login$"))
    check(page.context.request.get(ME).status == 403, "Shared logout must invalidate the real session")


def test_generic_server_validation_focuses_first_field_without_guessing_details(auth_page):
    page = auth_page
    form(page, "/register")
    email, password = identity()
    fill(page, email, password)

    def invalid_type(route):
        payload = route.request.post_data_json
        payload["password"] = 123456789
        route.continue_(post_data=json.dumps(payload))

    page.route("**" + REGISTER, invalid_type)
    with page.expect_response(lambda response: response.url.endswith(REGISTER)) as response:
        page.get_by_role("button", name="Зарегистрироваться", exact=True).click()
    check(response.value.status == 400, "Expected real backend validation refusal")
    check("fields" not in response.value.json()["error"], "Registration deliberately uses a generic validation error")
    expect(page.get_by_role("alert")).to_be_visible()
    expect(page.get_by_label("Email", exact=True)).to_be_focused()
    expect(page.get_by_label("Email", exact=True)).to_have_attribute("aria-invalid", "true")
    check(page.context.request.get(ME).status == 403, "Invalid registration must not authenticate")
