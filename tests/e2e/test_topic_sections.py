"""Real reader, sections API, owned PostgreSQL and the existing read transaction."""
import re

import pytest
from playwright.sync_api import expect

from tests.e2e.test_auth_ui import check
from tests.e2e.test_learning_ui import signed_in
from tests.e2e.test_assessment_ui import request_post


pytestmark = pytest.mark.cross_browser
SIZES = [{"width": 1280, "height": 900}, {"width": 390, "height": 844}]


def open_sections(page, topic_id, language="ru", section_id=None):
    path = "/topics/" + topic_id + ("?language=en" if language == "en" else "")
    page.goto(path + ("#section-" + section_id if section_id else ""))
    expect(page.locator(".reader-section")).to_have_count(2)
    expect(page.locator(".article-end")).to_have_count(1)


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_sections_anchors_ru_en_reload_history_and_keyboard(auth_page, auth_app, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    topic_id = learning_topics["first"]
    ids = auth_app.learning_data("sections", [topic_id])["sections"]
    signed_in(page)
    reads, gets = [], []
    def record(request):
        if request.method == "POST" and request.url.endswith("/topics/" + topic_id + "/read/"):
            reads.append(1)
        if request.method == "GET" and "/topics/" + topic_id + "/sections/" in request.url:
            gets.append(1)
    page.on("request", record)
    open_sections(page, topic_id, section_id=ids[0])
    expect(page.locator(".reader-section h2")).to_have_text(["Раздел 1", "Раздел 2"])
    expect(page.locator("#section-" + ids[0])).to_be_focused()
    expect(page.get_by_text("Hidden draft section", exact=True)).to_have_count(0)
    page.locator(".reader-section .article-body").first.evaluate("node => node.scrollIntoView({block: 'end'})")
    check(page.context.request.get("/api/v1/progress/").json() == {"data": []}, "Intermediate section must not mark the Topic read")
    check(not reads, "No Read request is allowed at an intermediate end")
    next_link = page.get_by_role("link", name="Следующий раздел", exact=True)
    next_link.focus()
    next_link.press("Enter")
    expect(page).to_have_url(re.compile(r"#section-" + ids[1] + "$"))
    expect(page.locator("#section-" + ids[1])).to_be_focused()
    expect(page.locator('.section-navigation a[aria-current="location"]')).to_have_text("Раздел 2")
    check(len(gets) == 1 and not reads, "Anchor navigation must not reload content or write Read")
    page.get_by_role("radio", name="English", exact=True).check()
    expect(page.locator(".reader-section h2")).to_have_text(["Section 1", "Section 2"])
    expect(page.get_by_role("radio", name="English", exact=True)).to_be_focused()
    expect(page).to_have_url(re.compile(r"\?language=en#section-" + ids[1] + "$"))
    page.reload()
    expect(page.locator("#section-" + ids[1])).to_be_focused()
    page.get_by_role("link", name="Предыдущий раздел", exact=True).click()
    expect(page.locator("#section-" + ids[0])).to_be_focused()
    page.go_back()
    expect(page.locator("#section-" + ids[1])).to_be_focused()
    page.go_forward()
    expect(page.locator("#section-" + ids[0])).to_be_focused()
    check(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Sections must fit the mobile viewport")
    check(not reads, "Heading/anchor navigation must not imply reaching the final end")


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
@pytest.mark.parametrize("language", ["ru", "en"])
def test_last_section_read_survives_translation_failure_and_one_pending_post(auth_page, auth_app, learning_topics, size, language):
    page = auth_page
    page.set_viewport_size(size)
    topic_id = learning_topics["first"]
    auth_app.learning_data("sections", [topic_id])
    signed_in(page)
    held = []
    page.route("**/api/v1/topics/" + topic_id + "/read/", lambda route: held.append(route))
    open_sections(page, topic_id, language)
    page.locator(".reader-section .article-body").first.evaluate("node => node.scrollIntoView({block: 'end'})")
    check(not held, "Intermediate section must not send Read")
    page.locator(".article-end").scroll_into_view_if_needed()
    expect(page.locator(".reading-card .ui-loading")).to_have_text("Сохраняем отметку…")
    pattern = "**/api/v1/topics/" + topic_id + "/sections/?*"
    page.route(pattern, lambda route: route.abort("failed"))
    other = "en" if language == "ru" else "ru"
    page.get_by_role("radio", name="English" if other == "en" else "Русский", exact=True).check()
    expect(page.locator("main").get_by_role("alert")).to_have_text("Не удалось загрузить материалы. Проверьте соединение и повторите загрузку.")
    expect(page.locator(".article-end")).to_have_count(0)
    page.unroute(pattern)
    page.get_by_role("button", name="Повторить загрузку", exact=True).click()
    expect(page.locator(".reader-section")).to_have_count(2)
    page.locator(".article-end").scroll_into_view_if_needed()
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    check(len(held) == 1, "Reloading a translation must preserve the sole pending POST")
    held[0].continue_()
    expect(page.locator(".reading-card .ui-notice--success")).to_be_visible()
    before = page.context.request.get("/api/v1/progress/").json()
    page.get_by_role("radio", name="Русский" if other == "en" else "English", exact=True).check()
    expect(page.locator(".article-body").first).to_have_attribute("lang", language)
    page.locator(".article-end").scroll_into_view_if_needed()
    expect(page.locator(".reading-card .ui-notice--success")).to_be_visible()
    check(len(held) == 1 and page.context.request.get("/api/v1/progress/").json() == before, "RU/EN must preserve the first saved Read date")


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_sections_unpublish_hides_new_reader_but_keeps_attempt_and_progress(auth_page, auth_app, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    topic_id = learning_topics["first"]
    auth_app.learning_data("sections", [topic_id])
    signed_in(page)
    open_sections(page, topic_id)
    page.locator(".article-end").scroll_into_view_if_needed()
    expect(page.locator(".reading-card .ui-notice--success")).to_be_visible()
    started = request_post(page.context, "/api/v1/topics/" + topic_id + "/attempts/", {"language": "en"})
    check(started.status == 201, "Published topic must allow an independent English test")
    attempt_id = started.json()["data"]["attempt_id"]
    attempt = page.context.request.get("/api/v1/attempts/" + attempt_id + "/?language=en").json()
    progress = page.context.request.get("/api/v1/progress/").json()
    auth_app.learning_data("draft", [topic_id])
    page.reload()
    expect(page.locator("main h1")).to_have_text("Тема не найдена")
    for suffix in ("/sections/", "/"):
        response = page.context.request.get("/api/v1/topics/" + topic_id + suffix)
        check(response.status == 404 and response.json()["error"]["code"] == "not_found", "Unpublished sections must be hidden")
    check(page.context.request.get("/api/v1/attempts/" + attempt_id + "/?language=en").json() == attempt, "Old attempt must keep its snapshot projection")
    check(page.context.request.get("/api/v1/progress/").json() == progress, "Unpublish must retain the existing Read")
    check(request_post(page.context, "/api/v1/topics/" + topic_id + "/attempts/", {"language": "ru"}).status == 404, "Draft must reject new attempts")
