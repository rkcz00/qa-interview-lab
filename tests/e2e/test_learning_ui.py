import os
from pathlib import Path
import re

from playwright.sync_api import expect

from tests.e2e.test_auth_ui import check, fill, post, seed, LOGIN


def signed_in(page):
    email, password = seed(page.context)
    check(post(page.context, LOGIN, email, password).status == 200, "Synthetic login failed")
    return email, password


def topic_page(page, topic_id, language="ru"):
    response = page.goto("/topics/" + topic_id + ("?language=en" if language == "en" else ""))
    check(response is not None and response.status == 200, "Direct Learning SPA route must load")
    expect(page.get_by_role("heading", name="Основы тестирования" if language == "ru" else "Testing foundations", exact=True)).to_be_visible()
    expect(page.locator(".article-body")).to_be_visible()


def test_guest_returns_to_requested_learning_page_after_ui_login(auth_page, learning_topics):
    page = auth_page
    email, password = seed(page.context)
    target = "/topics/" + learning_topics["first"] + "?language=en"
    page.goto(target)
    expect(page).to_have_url(re.compile(r"/login$"))
    fill(page, email, password)
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page).to_have_url(re.compile(re.escape(target) + r"$"))
    expect(page.get_by_role("heading", name="Testing foundations", exact=True)).to_be_visible()
    check(page.context.request.get("/api/v1/progress/").json() == {"data": []}, "Visiting Learning must not create progress")


def test_catalog_only_published_with_stable_order_and_real_loading(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    held = []
    page.route("**/api/v1/topics/?*", lambda route: held.append(route))
    response = page.goto("/topics")
    check(response is not None and response.status == 200, "Catalog SPA route must load")
    expect(page.get_by_role("status")).to_have_text("Загружаем материалы…")
    page.wait_for_timeout(100)
    check(len(held) == 1, "One real catalog request is expected")
    held[0].continue_()
    expect(page.locator(".topic-list a")).to_have_text(["Основы тестирования", "Автоматизация"])
    expect(page.get_by_text("Невидимый черновик", exact=True)).to_have_count(0)
    page.get_by_role("link", name="Основы тестирования", exact=True).click()
    expect(page).to_have_url(re.compile(r"/topics/" + learning_topics["first"] + r"$"))
    expect(page.locator(".article-body")).to_contain_text("Проверяйте требования и риски.")


def test_ru_en_history_reload_glossary_and_safe_plain_text(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    attempted = []
    page.on("request", lambda request: attempted.append(1) if "/attempts/" in request.url else None)
    topic_page(page, learning_topics["first"])
    expect(page.locator(".glossary dt")).to_have_text(["Риск", "Оракул", "Качество"])
    expect(page.locator(".article-body")).to_contain_text("<script>")
    check(page.locator(".article-body script,.article-body img").count() == 0, "Content must render as text, not HTML")
    check(page.evaluate("window.qilInjected === undefined"), "Content must not execute JavaScript")
    page.locator(".glossary").scroll_into_view_if_needed()
    check(page.context.request.get("/api/v1/progress/").json() == {"data": []}, "Article/glossary must not mark read")
    page.get_by_role("radio", name="English", exact=True).check()
    expect(page).to_have_url(re.compile(r"\?language=en$"))
    expect(page.get_by_role("heading", name="Testing foundations", exact=True)).to_be_visible()
    expect(page.locator(".article-body")).to_contain_text("Check requirements and risks.")
    expect(page.locator(".article-body")).to_have_attribute("lang", "en")
    check(page.locator("html").get_attribute("lang") == "ru", "Material language must not change UI language")
    expect(page.locator(".glossary dt")).to_have_text(["Risk", "Oracle", "Quality"])
    page.reload()
    expect(page.get_by_role("radio", name="English", exact=True)).to_be_checked()
    expect(page.locator(".glossary dt")).to_have_text(["Risk", "Oracle", "Quality"])
    page.go_back()
    expect(page.get_by_role("heading", name="Основы тестирования", exact=True)).to_be_visible()
    page.go_forward()
    expect(page.get_by_role("heading", name="Testing foundations", exact=True)).to_be_visible()
    check(not attempted, "Learning must not create or retrieve attempts")
    check(auth_app.learning_data("info", [learning_topics["first"]])["read_count"] == 0, "Language changes must not create read marks")


def test_mark_read_csrf_double_click_reload_and_shared_language_progress(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    topic_page(page, topic_id)
    button = page.get_by_role("button", name="Отметить «Прочитано»", exact=True)
    expect(button).to_be_enabled()
    held = []
    page.route("**/api/v1/topics/" + topic_id + "/read/", lambda route: held.append(route))
    button.click()
    expect(page.get_by_role("button", name="Сохраняем отметку…", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Сохраняем отметку…", exact=True).evaluate("button => button.click()")
    page.wait_for_timeout(100)
    check(len(held) == 1, "Only one read POST may be sent")
    check(bool(held[0].request.headers.get("x-csrftoken")), "Read POST must include CSRF header")
    held[0].continue_()
    expect(page.get_by_role("button", name="Прочитано", exact=True)).to_be_disabled()
    before = page.context.request.get("/api/v1/progress/").json()
    page.reload()
    expect(page.get_by_role("button", name="Прочитано", exact=True)).to_be_disabled()
    page.get_by_role("radio", name="English", exact=True).check()
    expect(page.get_by_role("button", name="Прочитано", exact=True)).to_be_disabled()
    check(page.context.request.get("/api/v1/progress/").json() == before, "Language must preserve the same mark and its first timestamp")
    check(auth_app.learning_data("info", [topic_id])["read_count"] == 1, "Exactly one read mark must be stored")


def test_other_user_does_not_inherit_read_state(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    topic_page(page, topic_id)
    page.get_by_role("button", name="Отметить «Прочитано»", exact=True).click()
    expect(page.get_by_role("button", name="Прочитано", exact=True)).to_be_disabled()
    check(post(page.context, "/api/v1/auth/logout/").status == 204, "Synthetic logout failed")
    signed_in(page)
    topic_page(page, topic_id)
    expect(page.get_by_role("button", name="Отметить «Прочитано»", exact=True)).to_be_enabled()
    check(page.context.request.get("/api/v1/progress/").json() == {"data": []}, "User B must not see user A's mark")
    check(auth_app.learning_data("info", [topic_id])["read_count"] == 1, "User A's mark must be preserved")


def test_draft_and_missing_topics_have_the_same_safe_not_found(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    for topic_id in (learning_topics["draft"], "0"):
        with page.expect_response(lambda response: "/api/v1/topics/" + topic_id + "/?" in response.url) as result:
            page.goto("/topics/" + topic_id)
        check(result.value.status == 404, "Draft/missing topic must use real backend 404")
        expect(page.get_by_role("heading", name="Тема не найдена", exact=True)).to_be_visible()
        expect(page.locator(".article-body")).to_have_count(0)
        expect(page.get_by_text("Невидимый черновик", exact=True)).to_have_count(0)


def test_empty_catalog_and_safe_network_error_retry(auth_page):
    page = auth_page
    signed_in(page)
    page.route("**/api/v1/topics/?*", lambda route: route.abort("failed"))
    page.goto("/topics")
    expect(page.get_by_role("alert")).to_have_text("Не удалось загрузить материалы. Проверьте соединение и повторите загрузку.")
    page.unroute("**/api/v1/topics/?*")
    page.get_by_role("button", name="Повторить загрузку", exact=True).click()
    expect(page.get_by_role("heading", name="Опубликованных тем пока нет.", exact=True)).to_be_visible()


def test_read_failure_stays_unknown_and_real_csrf_refusal_can_be_rechecked(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    page.route("**/api/v1/progress/", lambda route: route.abort("failed"))
    topic_id = learning_topics["first"]
    topic_page(page, topic_id)
    expect(page.get_by_role("alert")).to_contain_text("Не удалось подтвердить отметку чтения.")
    expect(page.get_by_role("button", name="Отметить «Прочитано»", exact=True)).to_have_count(0)
    page.unroute("**/api/v1/progress/")
    page.get_by_role("button", name="Проверить отметку ещё раз", exact=True).click()
    expect(page.get_by_role("button", name="Отметить «Прочитано»", exact=True)).to_be_enabled()

    def without_csrf(route):
        route.continue_(headers={name: value for name, value in route.request.headers.items() if name.lower() != "x-csrftoken"})

    pattern = "**/api/v1/topics/" + topic_id + "/read/"
    page.route(pattern, without_csrf)
    page.get_by_role("button", name="Отметить «Прочитано»", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Не удалось подтвердить запрос.")
    check(page.context.request.get("/api/v1/progress/").json() == {"data": []}, "CSRF refusal must not save a mark")
    page.unroute(pattern)
    page.get_by_role("button", name="Проверить отметку ещё раз", exact=True).click()
    page.get_by_role("button", name="Отметить «Прочитано»", exact=True).click()
    expect(page.get_by_role("button", name="Прочитано", exact=True)).to_be_disabled()


def test_session_expiry_returns_to_login_and_back_to_learning(auth_page, learning_topics):
    page = auth_page
    email, password = signed_in(page)
    topic_id = learning_topics["first"]
    topic_page(page, topic_id)
    expect(page.get_by_role("button", name="Отметить «Прочитано»", exact=True)).to_be_enabled()
    check(post(page.context, "/api/v1/auth/logout/").status == 204, "Synthetic logout failed")
    page.get_by_role("button", name="Отметить «Прочитано»", exact=True).click()
    expect(page).to_have_url(re.compile(r"/login$"))
    fill(page, email, password)
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page).to_have_url(re.compile(r"/topics/" + topic_id + r"$"))
    expect(page.get_by_role("heading", name="Основы тестирования", exact=True)).to_be_visible()


def test_unpublishing_before_read_clears_content_and_progress_is_not_written(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    topic_page(page, topic_id)
    expect(page.get_by_role("button", name="Отметить «Прочитано»", exact=True)).to_be_enabled()
    auth_app.learning_data("draft", [topic_id])
    page.get_by_role("button", name="Отметить «Прочитано»", exact=True).click()
    expect(page.get_by_role("heading", name="Тема не найдена", exact=True)).to_be_visible()
    expect(page.locator(".article-body")).to_have_count(0)
    check(auth_app.learning_data("info", [topic_id])["read_count"] == 0, "Unpublished topic cannot receive a new mark")


def test_material_selector_keyboard_mobile_and_invalid_language(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    topic_page(page, topic_id)
    page.get_by_role("radio", name="Русский", exact=True).focus()
    page.keyboard.press("ArrowRight")
    expect(page.get_by_role("heading", name="Testing foundations", exact=True)).to_be_visible()
    for size, name in (({"width": 1280, "height": 1000}, "desktop"), ({"width": 375, "height": 812}, "mobile")):
        page.set_viewport_size(size)
        expect(page.locator(".glossary")).to_be_visible()
        check(page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Learning content must fit the viewport")
        visual = os.environ.get("QIL_LEARNING_VISUAL_DIR")
        if visual:
            directory = Path(visual).resolve()
            root = Path(__file__).resolve().parents[2]
            check(directory.parent == root / ".cache" and directory.name.startswith("qil019-"), "Unsafe visual target")
            directory.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(directory / (name + ".png")), full_page=True)
    page.goto("/topics/" + topic_id + "?language=de")
    expect(page.get_by_role("alert")).to_have_text("Выберите русский или английский язык материала.")
