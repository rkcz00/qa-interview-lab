import re

from playwright.sync_api import expect

from tests.e2e.test_auth_ui import check, fill, post, seed, LOGIN


def signed_in(page):
    email, password = seed(page.context)
    check(post(page.context, LOGIN, email, password).status == 200, "Synthetic login failed")
    return email, password


def topic_page(page, topic_id, language="ru"):
    route = "/topics/" + topic_id + ("?language=en" if language == "en" else "")
    check(page.request.get(route, headers={"Cache-Control": "no-cache"}).status == 200, "Direct Learning SPA route must return HTTP 200")
    response = page.goto(route)
    check(response is not None and response.status in (200, 304), "Browser Learning navigation must load or revalidate the page")
    expect(page.get_by_role("heading", name="Основы тестирования" if language == "ru" else "Testing foundations", exact=True)).to_be_visible()
    expect(page.locator(".article-body")).to_be_visible()


def read_article(page):
    page.locator(".article-end").scroll_into_view_if_needed()
    expect(page.locator(".reading-card .ui-notice--success")).to_have_text("Статья отмечена прочитанной.")


def test_guest_returns_to_home_catalog_after_ui_login(auth_page, learning_topics):
    page = auth_page
    email, password = seed(page.context)
    page.goto("/topics/" + learning_topics["first"] + "?language=en")
    expect(page).to_have_url(re.compile(r"/login$"))
    fill(page, email, password)
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page).to_have_url(re.compile(r"/$"))
    expect(page.locator(".topic-list a")).to_have_count(2)
    check(page.context.request.get("/api/v1/progress/").json() == {"data": []}, "Catalog must not mark an article")


def test_catalog_only_published_with_stable_order_and_real_loading(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    held = []
    page.route("**/api/v1/topics/?*", lambda route: held.append(route))
    page.goto("/topics")
    expect(page.locator("main .ui-loading")).to_have_text("Загружаем материалы…")
    page.wait_for_timeout(100)
    check(len(held) == 2, "Catalog and shared menu request the real catalog")
    for route in held:
        route.continue_()
    expect(page.locator(".topic-list a")).to_have_text(["Основы тестирования", "Автоматизация"])
    expect(page.get_by_text("Невидимый черновик", exact=True)).to_have_count(0)
    page.locator(".topic-list").get_by_role("link", name="Основы тестирования", exact=True).click()
    expect(page).to_have_url(re.compile(r"/topics/" + learning_topics["first"] + r"$"))


def test_ru_en_history_reload_glossary_and_safe_plain_text(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    topic_page(page, topic_id)
    expect(page.locator(".glossary dt")).to_have_text(["Риск", "Оракул", "Качество"])
    expect(page.locator(".article-body")).to_contain_text("<script>")
    check(page.locator(".article-body script,.article-body img").count() == 0, "Article must remain safe text")
    check(page.evaluate("window.qilInjected === undefined"), "Article must not execute scripts")
    read_article(page)
    before = page.context.request.get("/api/v1/progress/").json()
    page.get_by_role("radio", name="English", exact=True).check()
    expect(page.locator(".article-body")).to_have_attribute("lang", "en")
    expect(page.locator(".article-body")).to_contain_text("Check requirements and risks.")
    expect(page.locator(".glossary dt")).to_have_text(["Risk", "Oracle", "Quality"])
    page.reload()
    expect(page.get_by_role("radio", name="English", exact=True)).to_be_checked()
    page.go_back()
    expect(page.locator(".article-body")).to_have_attribute("lang", "ru")
    page.go_forward()
    expect(page.locator(".article-body")).to_have_attribute("lang", "en")
    check(page.context.request.get("/api/v1/progress/").json() == before, "Translations must preserve the first mark")
    check(auth_app.learning_data("info", [topic_id])["attempt_count"] == 0, "Reading must not start a test")


def test_automatic_read_csrf_duplicate_visibility_reload_and_languages(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    auth_app.learning_data("long_article", [topic_id])
    topic_page(page, topic_id)
    held = []
    page.route("**/api/v1/topics/" + topic_id + "/sections/*/read/", lambda route: held.append(route))
    check(page.context.request.get("/api/v1/progress/").json() == {"data": []}, "Opening a long article is not reading its end")
    page.locator(".article-end").scroll_into_view_if_needed()
    expect(page.locator(".reading-card .ui-loading")).to_have_text("Сохраняем отметку…")
    page.locator(".article-end").scroll_into_view_if_needed()
    page.wait_for_timeout(100)
    check(len(held) == 1 and bool(held[0].request.headers.get("x-csrftoken")), "One CSRF-protected automatic POST is required")
    held[0].continue_()
    read_article(page)
    before = page.context.request.get("/api/v1/progress/").json()
    page.reload()
    read_article(page)
    page.get_by_role("radio", name="English", exact=True).check()
    read_article(page)
    check(page.context.request.get("/api/v1/progress/").json() == before and len(held) == 1, "Reload and RU/EN must not create another mark")
    check(auth_app.learning_data("info", [topic_id])["read_count"] == 1, "Exactly one shared mark must be stored")


def test_other_user_does_not_inherit_read_state(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    auth_app.learning_data("long_article", [topic_id])
    topic_page(page, topic_id)
    read_article(page)
    check(post(page.context, "/api/v1/auth/logout/").status == 204, "Synthetic logout failed")
    signed_in(page)
    topic_page(page, topic_id)
    check(page.context.request.get("/api/v1/progress/").json() == {"data": []}, "User B must not inherit user A's mark")
    check(auth_app.learning_data("info", [topic_id])["read_count"] == 1, "User A's mark must remain")


def test_draft_and_missing_topics_have_the_same_safe_not_found(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    for topic_id in (learning_topics["draft"], "0"):
        with page.expect_response(lambda response: "/api/v1/topics/" + topic_id + "/sections/?" in response.url) as response:
            page.goto("/topics/" + topic_id)
        check(response.value.status == 404, "Draft and missing must use backend 404")
        legacy = page.context.request.get("/api/v1/topics/" + topic_id + "/")
        check(legacy.status == 404 and legacy.json() == response.value.json(), "Legacy Article must preserve the same safe 404")
        expect(page.get_by_role("heading", name="Тема не найдена", exact=True)).to_be_visible()
        expect(page.locator(".article-body")).to_have_count(0)
        expect(page.get_by_text("Невидимый черновик", exact=True)).to_have_count(0)


def test_empty_catalog_and_safe_network_error_retry(auth_page):
    page = auth_page
    signed_in(page)
    page.route("**/api/v1/topics/?*", lambda route: route.abort("failed"))
    page.goto("/")
    expect(page.locator("main").get_by_role("alert")).to_have_text("Не удалось загрузить материалы. Проверьте соединение и повторите загрузку.")
    page.unroute("**/api/v1/topics/?*")
    page.locator("main").get_by_role("button", name="Повторить загрузку", exact=True).click()
    expect(page.get_by_role("heading", name="Опубликованных тем пока нет.", exact=True)).to_be_visible()


def test_read_failure_stays_unknown_and_real_csrf_refusal_can_be_rechecked(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    auth_app.learning_data("long_article", [topic_id])
    reading_pattern = "**/api/v1/topics/" + topic_id + "/reading/**"
    page.route(reading_pattern, lambda route: route.abort("failed"))
    topic_page(page, topic_id)
    expect(page.locator("main").get_by_role("alert")).to_contain_text("Не удалось подтвердить отметку чтения.")
    def without_csrf(route):
        route.continue_(headers={name: value for name, value in route.request.headers.items() if name.lower() != "x-csrftoken"})
    pattern = "**/api/v1/topics/" + topic_id + "/sections/*/read/"
    page.route(pattern, without_csrf)
    page.unroute(reading_pattern)
    page.get_by_role("button", name="Проверить отметку ещё раз", exact=True).click()
    page.locator(".article-end").scroll_into_view_if_needed()
    expect(page.locator("main").get_by_role("alert")).to_contain_text("Не удалось подтвердить запрос.")
    check(page.context.request.get("/api/v1/progress/").json() == {"data": []}, "CSRF refusal must not save a mark")
    page.unroute(pattern)
    page.get_by_role("button", name="Проверить отметку ещё раз", exact=True).click()
    read_article(page)


def test_session_expiry_returns_to_login_and_then_home(auth_page, auth_app, learning_topics):
    page = auth_page
    email, password = signed_in(page)
    topic_id = learning_topics["first"]
    auth_app.learning_data("long_article", [topic_id])
    topic_page(page, topic_id)
    check(post(page.context, "/api/v1/auth/logout/").status == 204, "Synthetic logout failed")
    page.locator(".article-end").scroll_into_view_if_needed()
    expect(page).to_have_url(re.compile(r"/login$"))
    fill(page, email, password)
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page).to_have_url(re.compile(r"/$"))


def test_unpublishing_before_read_clears_content_without_saving(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics["first"]
    auth_app.learning_data("long_article", [topic_id])
    topic_page(page, topic_id)
    auth_app.learning_data("draft", [topic_id])
    page.locator(".article-end").scroll_into_view_if_needed()
    expect(page.get_by_role("heading", name="Тема не найдена", exact=True)).to_be_visible()
    expect(page.locator(".article-body")).to_have_count(0)
    check(auth_app.learning_data("info", [topic_id])["read_count"] == 0, "Draft must not receive a mark")


def test_material_selector_keyboard_mobile_and_invalid_language(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    topic_page(page, learning_topics["first"])
    page.get_by_role("radio", name="Русский", exact=True).focus()
    page.keyboard.press("ArrowRight")
    expect(page.locator(".article-body")).to_have_attribute("lang", "en")
    expect(page.get_by_role("radio", name="English", exact=True)).to_be_focused()
    for size in ({"width": 1280, "height": 900}, {"width": 390, "height": 844}):
        page.set_viewport_size(size)
        check(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Learning must fit viewport")
    page.goto("/topics/" + learning_topics["first"] + "?language=de")
    expect(page.locator("main").get_by_role("alert")).to_have_text("Выберите русский или английский язык материала.")
