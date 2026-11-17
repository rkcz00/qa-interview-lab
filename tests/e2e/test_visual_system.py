"""QIL-027: shared presentation, real requests and synthetic long articles."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.e2e.test_auth_ui import check, form
from tests.e2e.test_learning_ui import signed_in, topic_page
from tests.e2e.test_assessment_ui import choose_correct, result


SIZES = [{"width": 1280, "height": 900}, {"width": 390, "height": 844}]


def visual(page, name, size):
    target = os.environ.get("QIL_VISUAL_SYSTEM_DIR")
    if not target:
        return
    directory = Path(target).resolve()
    root = Path(__file__).resolve().parents[2]
    check(directory.parent == root / ".cache" and directory.name.startswith("qil027-"), "Unsafe visual output directory")
    directory.mkdir(parents=True, exist_ok=True)
    # Screenshots contain public synthetic content only; never filled auth forms.
    page.screenshot(path=str(directory / (name + "-" + str(size["width"]) + ".png")), full_page=True)


def fits(page):
    check(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "The page must not overflow horizontally")


def heading_style(page):
    return page.locator("h1").evaluate("element => { const s = getComputedStyle(element); return [s.fontSize, s.lineHeight, s.marginBottom] }")


def visible_keyboard_focus(page, control):
    control.focus()
    page.keyboard.press("Tab")
    page.keyboard.press("Shift+Tab")
    expect(control).to_be_focused()
    check(control.evaluate("element => element.matches(':focus-visible') && getComputedStyle(element).outlineStyle === 'solid' && getComputedStyle(element).outlineWidth === '3px'"),
          "Keyboard focus must have a visible shared outline")


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_shared_styles_on_all_auth_learning_assessment_progress_routes(auth_page, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    page.goto("/")
    expect(page.get_by_role("heading", name="QA Interview Lab", exact=True)).to_be_visible()
    expected_heading = heading_style(page)
    check(28 <= float(expected_heading[0][:-2]) <= 36, "Heading scale must remain within the shared readable range")
    visual(page, "home", size)
    for path, name in (("/register", "register"), ("/login", "login")):
        form(page, path)
        check(heading_style(page) == expected_heading, "Auth and learner headings must share one scale")
        button = page.locator("form button")
        expect(button).to_have_class("ui-button ui-button--primary")
        check(button.evaluate("element => element.type === 'submit' && element.getAttribute('aria-busy') === null"), "Idle auth submit must not announce loading")
        visible_keyboard_focus(page, page.get_by_label("Email", exact=True))
        visible_keyboard_focus(page, button)
        fits(page)
        visual(page, name, size)
    signed_in(page)
    page.goto("/session")
    expect(page.locator(".session-email")).to_be_visible()
    check(heading_style(page) == expected_heading, "Session must share heading tokens")
    visual(page, "session", size)
    page.goto("/topics")
    expect(page.locator(".topic-list a")).to_have_count(2)
    visual(page, "catalog", size)
    topic_id = learning_topics["first"]
    topic_page(page, topic_id)
    expect(page.locator(".reading-card .ui-notice--info")).to_have_attribute("role", "status")
    visual(page, "article", size)
    page.get_by_role("link", name="Пройти тест", exact=True).click()
    expect(page.get_by_role("heading", name="Начало теста", exact=True)).to_be_visible()
    visual(page, "test-start", size)
    page.get_by_role("button", name="Начать тест", exact=True).click()
    expect(page.locator(".question-card")).to_be_visible()
    previous = page.get_by_role("button", name="Предыдущий вопрос", exact=True)
    expect(previous).to_be_disabled()
    check(previous.get_attribute("aria-busy") is None, "A disabled previous button is not a pending request")
    check(previous.evaluate("element => getComputedStyle(element).cursor") == "not-allowed", "Static disabled controls must not use the wait cursor")
    visual(page, "attempt", size)
    choose_correct(page)
    page.get_by_role("button", name="Отправить тест", exact=True).click()
    result(page)
    check(heading_style(page) == expected_heading, "Results must share heading tokens")
    visual(page, "result", size)
    page.get_by_role("link", name="Посмотреть прогресс", exact=True).click()
    expect(page.get_by_role("link", name="Открыть сохранённый результат", exact=True)).to_have_count(1)
    check(heading_style(page) == expected_heading, "Progress must share heading tokens")
    visual(page, "progress", size)
    for route in ("/session", "/topics", "/progress"):
        page.goto(route)
        expect(page.get_by_role("navigation", name="Основная навигация").locator("a[aria-current]")).to_have_attribute("href", route)
        fits(page)


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_long_bilingual_article_wraps_without_transforming_text_or_focus(auth_page, auth_app, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    check(auth_app.learning_data("long_article", [learning_topics["first"]]) == {"long_article": "PASS"}, "Synthetic long article setup must succeed")
    signed_in(page)
    topic_id = learning_topics["first"]
    topic_page(page, topic_id)
    for language, name in (("ru", "Русский"), ("en", "English"), ("ru", "Русский")):
        control = page.get_by_role("radio", name=name, exact=True)
        control.check()
        article = page.locator(".article-body")
        expect(article).to_have_attribute("lang", language)
        response = page.context.request.get("/api/v1/topics/" + topic_id + "/?language=" + language)
        check(response.status == 200, "Article oracle must be the real learner API")
        body = response.json()["data"]["article_body"]
        check(article.text_content() == body, "Article text, paragraphs and URL must remain exactly as provided by API")
        check(article.evaluate("element => { const s = getComputedStyle(element); return s.whiteSpace === 'pre-wrap' && s.overflowWrap === 'anywhere' && parseFloat(s.lineHeight) / parseFloat(s.fontSize) >= 1.7 && element.scrollWidth <= element.clientWidth }"),
              "Long text needs preserved paragraphs, wrapping and readable line spacing")
        fits(page)
        if language == "en":
            expect(control).to_be_focused()
            visual(page, "long-article-en", size)
        elif name == "Русский":
            visual(page, "long-article-ru", size)
    page.get_by_role("radio", name="Русский", exact=True).focus()
    page.keyboard.press("ArrowRight")
    expect(page.locator(".article-body")).to_have_attribute("lang", "en")
    expect(page.get_by_role("radio", name="English", exact=True)).to_be_focused()
    fits(page)


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_busy_success_disabled_and_reduced_motion_states(auth_page, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    page.emulate_media(reduced_motion="reduce")
    signed_in(page)
    topic_id = learning_topics["first"]
    topic_page(page, topic_id)
    held = []
    page.route("**/api/v1/topics/" + topic_id + "/read/", lambda route: held.append(route))
    page.get_by_role("button", name="Отметить «Прочитано»", exact=True).click()
    pending = page.get_by_role("button", name="Сохраняем отметку…", exact=True)
    expect(pending).to_have_attribute("aria-busy", "true")
    expect(pending).to_be_disabled()
    expect(page.locator(".ui-loading")).to_have_attribute("role", "status")
    check(pending.evaluate("element => getComputedStyle(element).cursor === 'wait' && getComputedStyle(element, '::before').animationName === 'none'"),
          "Busy state must honor reduced motion while preserving its label")
    pending.evaluate("element => element.click()")
    page.wait_for_timeout(100)
    check(len(held) == 1, "Busy submit must not send a second request")
    visual(page, "read-loading", size)
    held[0].continue_()
    marked = page.get_by_role("button", name="Прочитано", exact=True)
    expect(marked).to_be_disabled()
    check(marked.get_attribute("aria-busy") is None, "Saved state must stop announcing loading")
    expect(page.locator(".ui-notice--success")).to_have_text("Статья отмечена прочитанной.")
    visual(page, "read-success", size)
    fits(page)


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_shared_errors_empty_state_and_form_focus(auth_page, auth_app, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    form(page, "/login")
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page.get_by_label("Email", exact=True)).to_be_focused()
    expect(page.get_by_label("Email", exact=True)).to_have_attribute("aria-invalid", "true")
    visual(page, "form-validation", size)
    signed_in(page)
    page.goto("/topics/" + learning_topics["draft"])
    expect(page.locator(".ui-notice--error")).to_have_text("Тема не найдена или недоступна.")
    expect(page.locator(".ui-notice--error")).to_have_attribute("role", "alert")
    fits(page)
    visual(page, "not-found", size)
    check(auth_app.learning_data("draft", learning_topics["ids"])["draft"] == "PASS", "Only owned topics may be hidden for empty state")
    page.goto("/topics")
    expect(page.locator(".ui-empty h2")).to_have_text("Опубликованных тем пока нет.")
    visual(page, "empty-catalog", size)
    page.goto("/progress")
    expect(page.locator(".ui-empty")).to_have_count(2)
    fits(page)
    visual(page, "empty-progress", size)
