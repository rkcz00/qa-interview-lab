"""Completion and reset UI against real Django/PostgreSQL; faults affect transport only."""
import json
import re
from time import monotonic

import pytest
from playwright.sync_api import expect

from tests.e2e.test_assessment_ui import request_post
from tests.e2e.test_auth_ui import check, post, LOGIN
from tests.e2e.test_learning_ui import signed_in
from tests.e2e.test_progress_ui import complete, open_progress, overall


pytestmark = pytest.mark.cross_browser
SIZES = [{"width": 1280, "height": 900}, {"width": 390, "height": 844}]
RESET = "/api/v1/progress/reset/"
COMPLETION = "/api/v1/completion-progress/"


def card(page, topic_id):
    return page.locator('main .completion-topic[data-topic-id="' + topic_id + '"]')


def field(page, topic_id, label):
    return card(page, topic_id).locator(".completion-statuses > div").filter(has=page.get_by_text(label, exact=True)).locator("dd")


def shown(page, percentage):
    expect(page.locator("main .overall-percentage")).to_have_text(percentage)
    expect(page.locator(".topic-sidebar .overall-percentage")).to_have_text(percentage)


def wait_routes(page, routes):
    deadline = monotonic() + 8
    while not routes and monotonic() < deadline:
        page.wait_for_timeout(25)
    check(bool(routes), "Expected the controlled real HTTP request")


def dialog(page):
    page.locator("main .reset-trigger").click()
    modal = page.get_by_role("dialog", name="Подтвердите сброс прогресса", exact=True)
    expect(modal).to_be_visible()
    return modal


def agree(modal):
    modal.get_by_role("checkbox").check()


def click_confirm(modal):
    modal.get_by_role("button", name="Сбросить весь прогресс", exact=True).click()


def prepare_read(page, topic_id, size):
    page.set_viewport_size(size)
    identity = signed_in(page)
    check(request_post(page.context, f"/api/v1/topics/{topic_id}/read/", {}).status == 200, "Create an isolated read mark")
    open_progress(page)
    shown(page, "15%")
    return identity


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_completion_displays_real_30_70_30_35_35_statuses_counts_and_separate_mastery(auth_page, practice_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    signed_in(page)
    enabled, disabled = practice_topics["enabled"], practice_topics["disabled"]
    open_progress(page)
    shown(page, "0%")
    expect(page.locator("main .completion-topic")).to_have_count(3)
    catalog_titles = [topic["title"] for topic in page.context.request.get("/api/v1/topics/?language=ru").json()["data"]]
    expect(page.locator(".topic-menu a")).to_have_text(catalog_titles)
    expect(field(page, enabled, "Статья")).to_have_text("Не прочитано")
    expect(field(page, enabled, "Тест")).to_have_text("Не пройдено")
    expect(field(page, enabled, "Практика")).to_have_text("Не пройдено")
    expect(field(page, disabled, "Практика")).to_have_text("Нет опубликованной практики")
    expect(field(page, practice_topics["draft_task"], "Практика")).to_have_text("Нет опубликованной практики")
    check(request_post(page.context, f"/api/v1/topics/{enabled}/read/", {}).status == 200, "Read mark")
    complete(page.context, enabled, correct=False)
    work = request_post(page.context, f"/api/v1/topics/{enabled}/practice/submissions/", {"language": "en"})
    check(work.status == 201, "Failed submitted test still opens Practice after Read")
    identifier = work.json()["data"]["submission_id"]
    check(request_post(page.context, f"/api/v1/practice-submissions/{identifier}/submit/", {"language": "en", "answer_text": "3"}).status == 200, "Synthetic incorrect Practice submit")
    open_progress(page)
    shown(page, "10%")
    expect(field(page, enabled, "Практика")).to_have_text("Неуспешно")
    retry = request_post(page.context, f"/api/v1/topics/{enabled}/practice/submissions/", {"language": "en"})
    check(retry.status == 201, "A new own Practice work")
    identifier = retry.json()["data"]["submission_id"]
    check(request_post(page.context, f"/api/v1/practice-submissions/{identifier}/submit/", {"language": "en", "answer_text": "2"}).status == 200, "Synthetic Practice submit")
    open_progress(page)
    shown(page, "21,67%")
    expect(card(page, enabled).locator(".topic-completion-percentage")).to_have_text("Прогресс темы: 65%")
    expect(field(page, enabled, "Тест")).to_contain_text("Неуспешно")
    expect(field(page, enabled, "Тест")).to_contain_text("0 из 2 верных ответов")
    expect(field(page, enabled, "Практика")).to_have_text("Успешно")
    expect(field(page, enabled, "Освоение")).to_have_text("Пока не освоена")
    complete(page.context, enabled)
    complete(page.context, enabled, correct=False)
    check(request_post(page.context, f"/api/v1/topics/{disabled}/read/", {}).status == 200, "Read without Practice")
    complete(page.context, disabled)
    open_progress(page)
    shown(page, "66,67%")
    expect(field(page, enabled, "Тест")).to_contain_text("2 из 2 верных ответов")
    expect(field(page, enabled, "Освоение")).to_have_text("Тема освоена")
    expect(card(page, disabled).locator(".topic-completion-percentage")).to_have_text("Прогресс темы: 100%")
    check(request_post(page.context, f"/api/v1/practice-submissions/{identifier}/delete/", {}).status == 204, "Delete only the correct work created by this scenario")
    open_progress(page)
    shown(page, "55%")
    expect(card(page, enabled).locator(".topic-completion-percentage")).to_have_text("Прогресс темы: 65%")
    expect(field(page, enabled, "Практика")).to_have_text("Неуспешно")
    expect(field(page, enabled, "Освоение")).to_have_text("Тема освоена")
    expect(page.locator(".attempt-history-list,.topic-progress-list")).to_have_count(0)
    check(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Completion must fit viewport")


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_reset_dialog_cancel_keyboard_double_click_200_get_and_ownership(auth_page, auth_app, practice_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    signed_in(page)
    first, second = practice_topics["enabled"], practice_topics["disabled"]
    check(request_post(page.context, f"/api/v1/topics/{first}/read/", {}).status == 200, "Own Read setup")
    attempt_id = complete(page.context, first)
    started = request_post(page.context, f"/api/v1/topics/{first}/practice/submissions/", {"language": "ru"})
    check(started.status == 201, "Own Practice setup")
    submission_id = started.json()["data"]["submission_id"]
    check(request_post(page.context, f"/api/v1/practice-submissions/{submission_id}/submit/", {"language": "ru", "answer_text": "2"}).status == 200, "Own Practice result")
    open_progress(page)
    shown(page, "33,33%")
    context = page.context.browser.new_context(base_url=auth_app.url)
    other = context.new_page()
    try:
        signed_in(other)
        check(request_post(context, f"/api/v1/topics/{second}/read/", {}).status == 200, "Second user's own data")
        foreign = context.request.get(COMPLETION).json()
        posts = []
        page.on("request", lambda request: posts.append(1) if request.url.endswith(RESET) and request.method == "POST" else None)
        modal = dialog(page)
        expect(modal.get_by_role("button", name="Отмена", exact=True)).to_be_focused()
        expect(modal.get_by_role("button", name="Сбросить весь прогресс", exact=True)).to_be_disabled()
        expect(modal).to_contain_text("PracticeSubmission")
        expect(modal).to_contain_text("Аккаунт и учебный контент не удаляются")
        expect(modal).to_contain_text("Операция необратима")
        page.keyboard.press("Shift+Tab")
        check(modal.evaluate("dialog => dialog.contains(document.activeElement)"), "Keyboard focus must remain inside modal")
        page.keyboard.press("Escape")
        expect(modal).not_to_be_visible()
        expect(page.locator("main .reset-trigger")).to_be_focused()
        modal = dialog(page)
        agree(modal)
        modal.get_by_role("button", name="Отмена", exact=True).click()
        check(not posts, "Cancelled dialog must not POST")
        modal = dialog(page)
        agree(modal)
        held_post, held_get = [], []
        page.route("**" + RESET, lambda route: held_post.append(route))
        confirm = modal.get_by_role("button", name="Сбросить весь прогресс", exact=True)
        expect(confirm).to_be_enabled()
        confirm.evaluate("button => { button.click(); button.click() }")
        wait_routes(page, held_post)
        expect(modal.get_by_role("button", name="Сбрасываем прогресс…", exact=True)).to_be_disabled()
        shown(page, "33,33%")
        page.route("**" + COMPLETION, lambda route: held_get.append(route))
        held_post[0].continue_()
        expect(modal.get_by_role("status")).to_have_text("Проверяем актуальный прогресс…")
        wait_routes(page, held_get)
        shown(page, "33,33%")
        check(len(posts) == 1 and len(held_get) == 1, "One reset POST and one follow-up completion GET")
        held_get[0].continue_()
        expect(modal).not_to_be_visible()
        shown(page, "0%")
        expect(page.locator("main").get_by_role("status")).to_have_text("Прогресс сброшен. Актуальные данные загружены.")
        expect(page.locator("main .reset-trigger")).to_be_focused()
        expect(field(page, first, "Статья")).to_have_text("Не прочитано")
        check(page.context.request.get(f"/api/v1/attempts/{attempt_id}/").status == 404, "Old own attempt must remain deleted")
        check(page.context.request.get(f"/api/v1/practice-submissions/{submission_id}/").status == 404, "Old own PracticeSubmission must remain deleted")
        check(context.request.get(COMPLETION).json() == foreign, "Reset must preserve the other user")
    finally:
        context.close()


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
@pytest.mark.parametrize("failure", ["validation", "csrf", "conflict"])
def test_reset_rejections_keep_previous_display_and_focus_safe_error(auth_page, learning_topics, size, failure):
    page = auth_page
    prepare_read(page, learning_topics["first"], size)
    before = page.context.request.get(COMPLETION).json()
    posts = []

    def reject(route):
        posts.append(1)
        if failure == "validation":
            payload = json.loads(route.request.post_data)
            payload["confirmation"] = "invalid"
            route.continue_(post_data=json.dumps(payload))
        else:
            headers = dict(route.request.headers)
            if failure == "csrf":
                headers.pop("x-csrftoken", None)
            else:
                headers["x-progress-generation"] = "9223372036854775807"
            route.continue_(headers=headers)

    page.route("**" + RESET, reject)
    modal = dialog(page)
    agree(modal)
    click_confirm(modal)
    expect(modal.get_by_role("alert")).to_be_visible()
    expect(modal.get_by_role("alert")).to_be_focused()
    shown(page, "15%")
    check(len(posts) == 1, "A rejected reset must not retry automatically")
    check(page.context.request.get(COMPLETION).json() == before, "Rejected reset must not mutate data")


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
@pytest.mark.parametrize("failure", ["network", "timeout"])
def test_lost_reset_response_requires_get_and_explicit_identical_receipt_retry(auth_page, learning_topics, size, failure):
    page = auth_page
    if failure == "timeout":
        # Only reset loses its response; normal GET/CSRF deadlines stay unchanged.
        page.add_init_script("""const originalFetch = window.fetch.bind(window);
            window.fetch = (input, init) => {
                const url = new URL(input instanceof Request ? input.url : String(input), location.origin);
                const reset = init?.method === 'POST' && url.pathname.endsWith('/progress/reset/');
                return originalFetch(input, reset ? {...init, signal: AbortSignal.timeout(1500)} : init);
            };""")
    first, second = learning_topics["first"], learning_topics["second"]
    prepare_read(page, first, size)
    posts = []

    def lose_once(route):
        posts.append((route.request.post_data, route.request.headers.get("x-progress-generation")))
        if len(posts) == 1:
            response = route.fetch()
            check(response.status == 200, "Real reset must commit before the response is lost")
            if failure == "network":
                route.abort("failed")
        else:
            route.continue_()

    page.route("**" + RESET, lose_once)
    modal = dialog(page)
    agree(modal)
    click_confirm(modal)
    expect(modal.get_by_role("alert")).to_contain_text("сброс мог выполниться")
    shown(page, "15%")
    check(page.context.request.get(COMPLETION).json()["data"]["progress_generation"] == "2", "Transport failure must not invent server rollback")
    check(request_post(page.context, f"/api/v1/topics/{second}/read/", {}, generation="2").status == 200, "New work after reset")
    modal.get_by_role("button", name="Проверить состояние", exact=True).click()
    expect(modal.get_by_role("button", name="Повторить тот же запрос", exact=True)).to_be_enabled()
    check(len(posts) == 1, "Verification GET must not POST")
    expect(field(page, first, "Статья")).to_have_text("Прочитано")
    modal.get_by_role("button", name="Повторить тот же запрос", exact=True).click()
    expect(modal).not_to_be_visible()
    check(len(posts) == 2 and posts[0] == posts[1], "Retry must keep the UUID, original generation and payload")
    expect(field(page, first, "Статья")).to_have_text("Не прочитано")
    expect(field(page, second, "Статья")).to_have_text("Прочитано")
    shown(page, "15%")


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_acknowledged_reset_with_get_failure_preserves_values_and_retries_get_only(auth_page, learning_topics, size):
    page = auth_page
    prepare_read(page, learning_topics["first"], size)
    committed, posts, gets = [], [], []

    def commit(route):
        posts.append(1)
        response = route.fetch()
        check(response.status == 200, "Reset receipt")
        committed.append(True)
        route.fulfill(response=response)

    def fail_get_once(route):
        gets.append(1)
        if committed and len(gets) == 1:
            route.abort("failed")
        else:
            route.continue_()

    page.route("**" + RESET, commit)
    page.route("**" + COMPLETION, fail_get_once)
    modal = dialog(page)
    agree(modal)
    click_confirm(modal)
    expect(modal.get_by_role("alert")).to_contain_text("Сервер подтвердил сброс")
    shown(page, "15%")
    modal.get_by_role("button", name="Загрузить актуальный прогресс", exact=True).click()
    expect(modal).not_to_be_visible()
    shown(page, "0%")
    check(len(posts) == 1 and len(gets) == 2, "GET retry must not repeat reset")


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_session_loss_during_reset_hides_private_state_and_preserves_account_data(auth_page, learning_topics, size):
    page = auth_page
    identity = prepare_read(page, learning_topics["first"], size)
    modal = dialog(page)
    agree(modal)
    check(post(page.context, "/api/v1/auth/logout/").status == 204, "Expire the synthetic session")
    click_confirm(modal)
    expect(page).to_have_url(re.compile(r"/login$"))
    expect(page.locator(".completion-topic,.overall-progress,dialog[open]")).to_have_count(0)
    check(post(page.context, LOGIN, *identity).status == 200, "The account survives session loss")
    open_progress(page)
    shown(page, "15%")


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_draft_empty_catalog_loading_and_reset_of_hidden_own_read(auth_page, auth_app, learning_topics, size):
    page = auth_page
    prepare_read(page, learning_topics["first"], size)
    auth_app.learning_data("draft", [learning_topics["first"], learning_topics["second"]])
    held = []
    page.route("**" + COMPLETION, lambda route: held.append(route))
    page.reload()
    expect(page.locator("main .ui-loading")).to_have_text("Загружаем прогресс…")
    expect(page.locator("main .overall-progress")).to_have_count(0)
    wait_routes(page, held)
    held[0].continue_()
    page.unroute("**" + COMPLETION)
    shown(page, "0%")
    expect(page.locator("main .ui-empty")).to_have_text("Опубликованных тем пока нет.")
    expect(page.locator("main .completion-topic")).to_have_count(0)
    modal = dialog(page)
    agree(modal)
    click_confirm(modal)
    expect(modal).not_to_be_visible()
    check(page.context.request.get("/api/v1/progress/").json() == {"data": []}, "Reset also removes own Draft read marks")


@pytest.mark.parametrize("size", SIZES, ids=["desktop", "mobile"])
def test_other_tab_logout_clears_frozen_private_view_even_after_uncertain_reset(auth_page, learning_topics, size):
    page = auth_page
    prepare_read(page, learning_topics["first"], size)

    def lose_response(route):
        response = route.fetch()
        check(response.status == 200, "The synthetic reset commits before losing its response")
        route.abort("failed")

    page.route("**" + RESET, lose_response)
    modal = dialog(page)
    agree(modal)
    click_confirm(modal)
    expect(modal.get_by_role("alert")).to_contain_text("сброс мог выполниться")
    shown(page, "15%")
    sibling = page.context.new_page()
    try:
        sibling.goto("/session")
        sibling.get_by_role("button", name="Выйти", exact=True).first.click()
        expect(page).to_have_url(re.compile(r"/login$"))
        expect(page.locator(".completion-topic,.overall-progress,dialog[open]")).to_have_count(0)
    finally:
        sibling.close()
