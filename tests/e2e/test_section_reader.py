"""QIL-044: real separate reader, verified temporary PostgreSQL, no critical-path mocks."""
import re
import time

import pytest
from playwright.sync_api import expect

from tests.e2e.test_auth_ui import check
from tests.e2e.test_learning_ui import signed_in
from tests.e2e.test_assessment_ui import request_post
from tests.e2e.reader_helpers import contents, open_reader, read_current, reading

pytestmark = pytest.mark.cross_browser
SIZES = [{"width": 1280, "height": 900}, {"width": 390, "height": 844}]


def sections(auth_app, learning_topics):
    topic_id = learning_topics["first"]
    ids = auth_app.learning_data("sections", [topic_id])["sections"]
    return topic_id, ids


def writes(page, topic_id):
    requests = []
    page.on("request", lambda r: requests.append(r.url) if r.method == "POST" and
            "/topics/" + topic_id + "/sections/" in r.url and r.url.endswith("/read/") else None)
    return requests


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_page_session_check_precedes_reader_load_and_fast_history_keeps_focus(auth_page, auth_app, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    topic_id, ids = sections(auth_app, learning_topics)
    signed_in(page)
    bodies, held = [], []
    posts = writes(page, topic_id)
    prefix = "/api/v1/topics/" + topic_id + "/sections/"

    def record(request):
        if request.method == "GET" and prefix in request.url:
            bodies.append(request.url.split(prefix, 1)[1].split("/", 1)[0])

    page.on("request", record)
    open_reader(page, topic_id, "ru", ids[0])
    expect(page.locator("main h1")).to_be_focused()
    pattern = "**/api/v1/auth/me/"
    page.route(pattern, lambda route: held.append(route))

    def wait_for_checks(number):
        deadline = time.monotonic() + 8
        while len(held) < number:
            check(time.monotonic() < deadline, "The route must check its real current session")
            page.wait_for_timeout(25)

    page.get_by_role("link", name="Следующий раздел", exact=True).click()
    wait_for_checks(1)
    expect(page.locator(".article-body,.article-end")).to_have_count(0)
    expect(page.get_by_role("radio", name="English", exact=True)).to_have_count(0)
    check(bodies == [ids[0]] and not posts, "Unchecked page must not fetch a body or write Read")
    page.go_back()
    wait_for_checks(2)
    for route in list(held):
        route.continue_()
    page.unroute(pattern)
    expect(page.locator("main h1")).to_have_text("Раздел 1")
    expect(page.locator("main h1")).to_be_focused()
    check(bodies == [ids[0], ids[0]], "A cancelled session check must not fetch the abandoned section")
    held_bodies = []
    body_pattern = "**/api/v1/topics/" + topic_id + "/sections/" + ids[1] + "/?*"
    page.route(body_pattern, lambda route: held_bodies.append(route))
    page.go_forward()
    deadline = time.monotonic() + 8
    while not held_bodies:
        check(time.monotonic() < deadline, "The verified route must load its selected real body")
        page.wait_for_timeout(25)
    expect(page.get_by_role("radio", name="English", exact=True)).to_be_disabled()
    expect(page.locator(".article-body,.article-end")).to_have_count(0)
    held_bodies[0].continue_()
    page.unroute(body_pattern)
    # Act immediately: the new page must never expose the previous page's controls.
    page.get_by_role("radio", name="English", exact=True).check()
    expect(page.locator("main h1")).to_have_text("Section 2")
    expect(page.locator(".article-body")).to_have_attribute("lang", "en")
    expect(page.get_by_role("radio", name="English", exact=True)).to_be_focused()
    check(set(bodies) == set(ids), "Each body request must belong to a selected Published section")
    check(not posts, "Session checks and heading navigation must not imply reading")
    read_current(page, topic_id, ids[1])
    check(len(posts) == 1, "Only the visible current section end may write Read")
    check(reading(page.context, topic_id)["sections"][0]["read_at"] is None, "The abandoned first section must remain unread")


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_contents_one_body_partial_read_language_neighbors_focus_and_full_read(auth_page, auth_app, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    topic_id, ids = sections(auth_app, learning_topics)
    signed_in(page)
    posts = writes(page, topic_id)
    legacy = []
    def record(request):
        if request.method == "GET" and re.search(r"/api/v1/topics/" + topic_id + r"/(?:sections/)?(?:\?.*)?$", request.url):
            legacy.append(1)
    page.on("request", record)
    contents(page, topic_id)
    expect(page.locator("main h1")).to_have_text("Основы тестирования")
    expect(page.locator(".section-navigation ol a")).to_have_text(["Раздел 1", "Раздел 2"])
    expect(page.locator(".glossary")).to_be_visible()
    expect(page.get_by_text("Hidden draft section", exact=True)).to_have_count(0)
    check(not posts and not legacy, "Contents/glossary must not request article bodies or write Read")
    page.locator(".section-navigation ol a").first.focus()
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"/sections/" + ids[0] + "$"))
    expect(page.locator("main h1")).to_have_text("Раздел 1")
    expect(page.locator("main h1")).to_be_focused()
    expect(page.locator(".article-body")).to_have_count(1)
    expect(page.locator('.section-navigation a[aria-current="page"]')).to_have_text("Раздел 1")
    check(not posts, "The start of a long section must not count as reading")
    partial = read_current(page, topic_id, ids[0])
    check(partial["reading"] == {"total_sections": 2, "read_sections": 1, "is_read": False, "completion_contribution": 15},
          "Intermediate section must remain partial")
    expect(page.locator(".reading-counter")).to_have_text("Прочитано разделов: 1 / 2")
    expect(page.locator("aside .overall-percentage")).to_have_text("7,5%")
    check(not legacy, "Reader must use only the single-section API")
    page.remove_listener("request", record)
    page.get_by_role("link", name="Пройти тест", exact=True).click()
    page.get_by_role("button", name="Начать тест", exact=True).click()
    expect(page.get_by_text("Сначала прочитайте все опубликованные разделы темы.", exact=True)).to_be_visible()
    check(auth_app.learning_data("info", [topic_id])["attempt_count"] == 0, "Gate must not create an Attempt")
    page.go_back()
    expect(page.locator("main h1")).to_have_text("Раздел 1")
    page.get_by_role("radio", name="English", exact=True).check()
    expect(page.locator("main h1")).to_have_text("Section 1")
    expect(page.get_by_role("radio", name="English", exact=True)).to_be_focused()
    next_link = page.get_by_role("link", name="Следующий раздел", exact=True)
    expect(next_link).to_have_attribute("href", "/topics/" + topic_id + "/sections/" + ids[1] + "?language=en")
    next_link.focus()
    next_link.press("Enter")
    expect(page.locator("main h1")).to_have_text("Section 2")
    expect(page.locator("main h1")).to_be_focused()
    expect(page.locator(".article-body")).to_have_count(1)
    expect(page.locator(".article-body")).to_have_attribute("lang", "en")
    completed = read_current(page, topic_id, ids[1])
    check(completed["reading"]["is_read"] and completed["reading"]["read_sections"] == 2, "Last remaining section completes Read")
    expect(page.locator(".reading-card .ui-notice--success")).to_have_text("Статья отмечена прочитанной.")
    expect(page.locator("aside .overall-percentage")).to_have_text("15%")
    before = completed["sections"][0]["read_at"]
    page.get_by_role("link", name="Предыдущий раздел", exact=True).click()
    expect(page.locator("main h1")).to_have_text("Section 1")
    page.go_back()
    expect(page.locator("main h1")).to_have_text("Section 2")
    page.go_forward()
    expect(page.locator("main h1")).to_have_text("Section 1")
    page.reload()
    expect(page.locator("main h1")).to_have_text("Section 1")
    check(reading(page.context, topic_id, "en")["sections"][0]["read_at"] == before, "RU/EN, history and reload preserve the first date")
    check(len(posts) == 2, "Each section has one POST")
    check(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Reader must fit viewport")


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
@pytest.mark.parametrize("language", ["ru", "en"])
def test_pending_survives_translation_failure_and_a_b_a_without_overwriting_b(auth_page, auth_app, learning_topics, size, language):
    page = auth_page
    page.set_viewport_size(size)
    topic_id, ids = sections(auth_app, learning_topics)
    signed_in(page)
    held = []
    pattern = "**/api/v1/topics/" + topic_id + "/sections/" + ids[0] + "/read/"
    page.route(pattern, lambda route: held.append(route))
    open_reader(page, topic_id, language, ids[0])
    page.locator(".article-end").scroll_into_view_if_needed()
    expect(page.locator(".reading-card .ui-loading")).to_have_text("Сохраняем отметку…")
    other = "en" if language == "ru" else "ru"
    failed = "**/api/v1/topics/" + topic_id + "/sections/" + ids[0] + "/?language=" + other
    page.route(failed, lambda route: route.abort("failed"))
    page.get_by_role("radio", name="English" if other == "en" else "Русский", exact=True).check()
    expect(page.locator("main").get_by_role("alert")).to_contain_text("Не удалось загрузить материалы.")
    expect(page.locator(".article-end")).to_have_count(0)
    page.unroute(failed)
    page.get_by_role("button", name="Повторить загрузку", exact=True).click()
    expect(page.locator(".article-body")).to_have_attribute("lang", other)
    page.get_by_role("link", name="Следующий раздел", exact=True).click()
    expect(page.locator("main h1")).to_have_text("Section 2" if other == "en" else "Раздел 2")
    page.go_back()
    expect(page.locator("main h1")).to_have_text("Section 1" if other == "en" else "Раздел 1")
    page.locator(".article-end").scroll_into_view_if_needed()
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    check(len(held) == 1, "A → B → A must preserve the sole pending A POST")
    page.go_forward()
    expect(page.locator("main h1")).to_have_text("Section 2" if other == "en" else "Раздел 2")
    held[0].continue_()
    expect(page.locator(".reading-counter")).to_have_text("Прочитано разделов: 1 / 2")
    expect(page.locator("main h1")).to_have_text("Section 2" if other == "en" else "Раздел 2")
    expect(page.locator(".article-body")).to_have_count(1)
    state = reading(page.context, topic_id)
    check(state["sections"][0]["read_at"] is not None and state["sections"][1]["read_at"] is None, "A response must not mark B")
    page.go_back()
    expect(page.locator(".article-body")).to_be_visible()
    page.locator(".article-end").scroll_into_view_if_needed()
    check(len(held) == 1, "Returning to a confirmed section cannot duplicate the POST")


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_hidden_zero_area_marker_needs_fresh_visible_geometry(auth_page, auth_app, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    topic_id, ids = sections(auth_app, learning_topics)
    signed_in(page)
    posts = writes(page, topic_id)
    open_reader(page, topic_id, "ru", ids[0])
    page.evaluate("""async () => {
        const marker = document.querySelector('.article-end');
        marker.style.display = 'none';
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
        document.dispatchEvent(new Event('visibilitychange'));
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
        document.dispatchEvent(new Event('visibilitychange'));
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        delete document.visibilityState;
    }""")
    check(not posts and reading(page.context, topic_id)["reading"]["read_sections"] == 0, "Hidden/0x0 must not be read")
    page.locator(".article-end").evaluate("node => node.style.removeProperty('display')")
    read_current(page, topic_id, ids[0])
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    check(len(posts) == 1, "A freshly visible end is written once")


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_legacy_hash_is_verified_replaced_and_foreign_section_is_hidden(auth_page, auth_app, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    topic_id, ids = sections(auth_app, learning_topics)
    signed_in(page)
    page.add_init_script("""window.qilReaderHeadings = 0;
        document.addEventListener('focusin', e => { if(e.target.tagName === 'H1') window.qilReaderHeadings++; });""")
    page.goto("/topics/" + topic_id + "?language=en#section-" + ids[1])
    expect(page).to_have_url(re.compile(r"/sections/" + ids[1] + r"\?language=en$"))
    expect(page.locator("main h1")).to_have_text("Section 2")
    expect(page.locator("main h1")).to_be_focused()
    check(page.evaluate("window.qilReaderHeadings === 1"), "Legacy redirect must focus only the final reader")
    foreign = reading(page.context, learning_topics["second"])["sections"][0]["section_id"]
    page.goto("/topics/" + topic_id + "#section-" + foreign)
    expect(page.locator(".section-navigation")).to_be_visible()
    expect(page.locator("main").get_by_role("alert")).to_have_text("Указанный раздел или якорь недоступен. Выберите раздел из оглавления.")
    expect(page.locator(".article-body,.article-end")).to_have_count(0)
    page.goto("/topics/" + topic_id + "/sections/" + foreign)
    expect(page.locator("main h1")).to_have_text("Раздел не найден")
    expect(page.locator(".article-body")).to_have_count(0)


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_uncertain_post_confirmed_by_get_refreshes_progress_without_another_post(auth_page, auth_app, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    topic_id, ids = sections(auth_app, learning_topics)
    signed_in(page)
    posts = writes(page, topic_id)

    def lost_reply(route):
        response = route.fetch()
        check(response.status == 200, "The real section write must complete before its reply is lost")
        route.abort("failed")

    page.route("**/api/v1/topics/" + topic_id + "/sections/" + ids[0] + "/read/", lost_reply)
    open_reader(page, topic_id, "ru", ids[0])
    expect(page.locator("aside .overall-percentage")).to_have_text("0%")
    page.locator(".article-end").scroll_into_view_if_needed()
    expect(page.locator(".reading-card").get_by_role("alert")).to_contain_text("Не удалось подтвердить отметку чтения.")
    check(reading(page.context, topic_id)["reading"]["read_sections"] == 1, "The server must retain the committed first mark")
    page.get_by_role("button", name="Проверить отметку ещё раз", exact=True).click()
    expect(page.locator(".reading-counter")).to_have_text("Прочитано разделов: 1 / 2")
    expect(page.locator("aside .overall-percentage")).to_have_text("7,5%")
    expect(page.get_by_role("button", name="Повторить сохранение", exact=True)).to_have_count(0)
    page.get_by_role("radio", name="English", exact=True).check()
    expect(page.locator("main h1")).to_have_text("Section 1")
    page.locator(".article-end").scroll_into_view_if_needed()
    check(len(posts) == 1, "GET confirmation and RU/EN must not repeat a committed section POST")


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_practice_gate_requires_sections_and_submitted_test(auth_page, practice_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    signed_in(page)
    topic_id = practice_topics["enabled"]
    contents(page, topic_id)
    expect(page.get_by_role("link", name="Открыть практику", exact=True)).to_be_visible()
    page.get_by_role("link", name="Открыть практику", exact=True).click()
    expect(page.get_by_role("button", name="Начать практику", exact=True)).to_be_disabled()
    expect(page.get_by_text("Сначала прочитайте все опубликованные разделы темы.", exact=True)).to_be_visible()
    denied = request_post(page.context, "/api/v1/topics/" + topic_id + "/practice/submissions/", {"language": "ru"})
    check(denied.status == 403 and denied.json()["error"]["code"] == "section_read_required", "Practice must enforce the section gate")
    metadata = reading(page.context, topic_id)
    section_id = metadata["sections"][0]["section_id"]
    open_reader(page, topic_id, "en", section_id)
    read_current(page, topic_id, section_id)
    denied = request_post(page.context, "/api/v1/topics/" + topic_id + "/practice/submissions/", {"language": "en"})
    check(denied.status == 403 and denied.json()["error"]["code"] == "practice_locked", "Read alone does not replace the submitted test")
