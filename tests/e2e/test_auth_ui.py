"""Auth UI uses the built SPA, real Django sessions/CSRF and isolated PostgreSQL."""

import os
from pathlib import Path
import re
from uuid import uuid4

from playwright.sync_api import expect
import pytest


LOGIN = "/api/v1/auth/login/"
REGISTER = "/api/v1/auth/register/"
ME = "/api/v1/auth/me/"


def check(condition, description):
    # Avoid including raw requests, cookies or credentials in assertion diagnostics.
    if not condition:
        pytest.fail(description, pytrace=False)


def identity():
    # Disjoint alphabets avoid accidental Django quick_ratio similarity between two UUIDs.
    return "auth-" + uuid4().hex + "@example.invalid", "Облако_Сосна_Февраль!" + uuid4().hex[:8]


def post(context, path, email=None, password=None):
    bootstrap = context.request.get("/api/v1/auth/csrf/")
    check(bootstrap.status == 200, "API bootstrap failed")
    token = bootstrap.json()["data"]["csrf_token"]
    payload = {} if email is None else {"email": email, "password": password}
    response = context.request.post(path, data=payload, headers={"X-CSRFToken": token})
    token = None
    return response


def seed(context):
    email, password = identity()
    check(post(context, REGISTER, email, password).status == 201, "Synthetic account creation failed")
    return email, password


def form(page, route):
    response = page.goto(route)
    check(response is not None and response.status == 200, "Direct SPA route must return HTTP 200")
    expect(page.get_by_label("Email", exact=True)).to_be_visible()
    expect(page.get_by_label("Пароль", exact=True)).to_be_visible()


def fill(page, email, password):
    try:
        page.get_by_label("Email", exact=True).fill(email)
        page.get_by_label("Пароль", exact=True).fill(password)
    except Exception:
        pytest.fail("Could not fill the Auth form; credentials were not logged", pytrace=False)


def test_direct_routes_guest_restore_and_home(auth_page):
    page = auth_page
    for route in ("/register", "/login"):
        form(page, route)
        check(page.locator("html").get_attribute("lang") == "ru", "Document language must be Russian")
    page.goto("/session")
    expect(page).to_have_url(re.compile(r"/login$"))
    expect(page.get_by_role("button", name="Войти", exact=True)).to_be_visible()
    page.goto("/")
    expect(page.get_by_role("heading", name="QA Interview Lab", exact=True)).to_be_visible()
    page.get_by_role("link", name="Регистрация", exact=True).click()
    expect(page).to_have_url(re.compile(r"/register$"))
    page.go_back()
    expect(page.get_by_role("heading", name="QA Interview Lab", exact=True)).to_be_visible()


def test_real_registration_login_reload_and_logout(auth_page):
    page = auth_page
    console = []
    page.on("console", lambda message: console.append(message.text))
    email, password = identity()
    form(page, "/register")
    fill(page, email.upper(), password)
    with page.expect_response(lambda response: response.url.endswith(REGISTER)) as registered:
        page.get_by_role("button", name="Зарегистрироваться", exact=True).click()
    check(registered.value.status == 201, "UI registration must create one account")
    expect(page).to_have_url(re.compile(r"/login$"))
    expect(page.get_by_role("status")).to_have_text("Аккаунт создан. Теперь войдите.")
    check(page.context.request.get(ME).status == 403, "Registration must not authenticate the browser")
    check(page.get_by_label("Email", exact=True).input_value() == email, "Use the normalized email returned by API")
    check(page.get_by_label("Пароль", exact=True).input_value() == "", "Registration password must be cleared")
    fill(page, email, password)
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page).to_have_url(re.compile(r"/session$"))
    expect(page.locator(".session-email")).to_have_text(email)
    page.reload()
    expect(page.locator(".session-email")).to_have_text(email)
    body = page.locator("body").inner_text()
    check(password not in body and not any(password in message for message in console), "Password must not appear in UI or logs")
    for cookie in page.context.cookies():
        if cookie["name"] in {"csrftoken", "sessionid"}:
            check(cookie["value"] not in body and not any(cookie["value"] in message for message in console),
                "Authentication cookies must not appear in UI or logs")
    check(page.evaluate("localStorage.length === 0 && sessionStorage.length === 0"), "Login must not persist credentials in web storage")
    page.get_by_role("button", name="Выйти", exact=True).click()
    expect(page).to_have_url(re.compile(r"/login$"))
    check(page.context.request.get(ME).status == 403, "Logout must invalidate authentication")
    page.goto("/session")
    expect(page).to_have_url(re.compile(r"/login$"))


def test_keyboard_form_navigation_and_enter_submit(auth_page):
    page = auth_page
    form(page, "/login")
    page.get_by_role("heading", name="Вход", exact=True).focus()
    page.keyboard.press("Tab")
    expect(page.get_by_label("Email", exact=True)).to_be_focused()
    page.keyboard.type("missing@example.invalid")
    page.keyboard.press("Tab")
    expect(page.get_by_label("Пароль", exact=True)).to_be_focused()
    page.keyboard.type("123")
    page.keyboard.press("Tab")
    expect(page.get_by_role("button", name="Войти", exact=True)).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.get_by_role("alert")).to_have_text("Неверный email или пароль.")


def test_client_validation_and_login_does_not_apply_registration_policy(auth_page):
    page = auth_page
    sent = []
    page.on("request", lambda request: sent.append(request.method) if request.url.endswith(REGISTER) else None)
    form(page, "/register")
    page.get_by_role("button", name="Зарегистрироваться", exact=True).click()
    expect(page.get_by_label("Email", exact=True)).to_be_focused()
    expect(page.get_by_text("Введите email.", exact=True)).to_be_visible()
    for password, text in (
        ("abc", "Пароль должен содержать не менее 8 символов."),
        ("1234567890", "Пароль не должен состоять только из цифр."),
        ("²²²²²²²²", "Пароль не должен состоять только из цифр."),
        ("password", "Выберите менее распространённый пароль."),
        ("learner123", "Пароль слишком похож на email."),
    ):
        fill(page, "learner@example.invalid", password)
        page.get_by_role("button", name="Зарегистрироваться", exact=True).click()
        expect(page.get_by_text(text, exact=True)).to_be_visible()
        expect(page.get_by_label("Пароль", exact=True)).to_be_focused()
    check(not sent, "Invalid registration must not send POST")
    form(page, "/login")
    fill(page, "missing@example.invalid", "123")
    with page.expect_response(lambda response: response.url.endswith(LOGIN)) as result:
        page.get_by_role("button", name="Войти", exact=True).click()
    check(result.value.status == 400, "Short login password must reach the server")
    expect(page.get_by_role("alert")).to_have_text("Неверный email или пароль.")
    expect(page.get_by_role("alert")).to_be_focused()
    check(page.get_by_label("Пароль", exact=True).input_value() == "", "Failed login must clear password")


def test_duplicate_email_uses_generic_validation_message(auth_page):
    page = auth_page
    email, password = seed(page.context)
    form(page, "/register")
    fill(page, email.upper(), password)
    with page.expect_response(lambda response: response.url.endswith(REGISTER)) as result:
        page.get_by_role("button", name="Зарегистрироваться", exact=True).click()
    check(result.value.status == 400, "Duplicate normalized email must fail validation")
    expect(page.get_by_role("alert")).to_have_text("Проверьте email и требования к паролю. Если аккаунт уже существует, войдите.")
    check(page.context.request.get(ME).status == 403, "Duplicate email must not log in")


def test_pending_and_double_submit_only_send_one_login(auth_page):
    page = auth_page
    email, password = seed(page.context)
    form(page, "/login?next=https://example.invalid&returnTo=/register")
    fill(page, email, password)
    held = []
    page.route("**" + LOGIN, lambda route: held.append(route))
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page.get_by_role("button", name="Входим…", exact=True)).to_be_disabled()
    expect(page.get_by_label("Email", exact=True)).to_be_disabled()
    expect(page.get_by_label("Пароль", exact=True)).to_be_disabled()
    page.locator("form").evaluate("form => { form.requestSubmit(); form.requestSubmit() }")
    page.wait_for_timeout(150)
    check(len(held) == 1, "Double submit must not send a second POST")
    held[0].continue_()
    expect(page).to_have_url(re.compile(r"/session$"))
    expect(page.locator(".session-email")).to_have_text(email)


@pytest.mark.parametrize("route", ["/login", "/register"])
def test_already_authenticated_race_restores_existing_session(auth_page, route):
    page = auth_page
    email, password = seed(page.context)
    form(page, route)
    check(post(page.context, LOGIN, email, password).status == 200, "Synthetic login failed")
    other_email, other_password = identity()
    fill(page, other_email, other_password)
    endpoint = LOGIN if route == "/login" else REGISTER
    with page.expect_response(lambda response: response.url.endswith(endpoint)) as result:
        page.get_by_role("button", name="Войти" if route == "/login" else "Зарегистрироваться", exact=True).click()
    check(result.value.status == 403 and result.value.json()["error"]["code"] == "already_authenticated",
        "Stale anonymous form must preserve the existing authenticated session")
    expect(page).to_have_url(re.compile(r"/session$"))
    expect(page.locator(".session-email")).to_have_text(email)
    page.goto("/register")
    expect(page).to_have_url(re.compile(r"/session$"))


def test_real_csrf_refusal_is_safe_and_has_no_automatic_retry(auth_page):
    page = auth_page
    form(page, "/register")
    email, password = identity()
    fill(page, email, password)
    requests = []

    def without_header(route):
        requests.append(1)
        headers = {key: value for key, value in route.request.headers.items() if key.lower() != "x-csrftoken"}
        route.continue_(headers=headers)

    page.route("**" + REGISTER, without_header)
    with page.expect_response(lambda response: response.url.endswith(REGISTER)) as result:
        page.get_by_role("button", name="Зарегистрироваться", exact=True).click()
    check(result.value.status == 403 and result.value.json()["error"]["code"] == "csrf_failed", "Expected real CSRF rejection")
    expect(page.get_by_role("alert")).to_contain_text("Не удалось подтвердить запрос.")
    check(len(requests) == 1, "CSRF failure must not replay registration")
    check(page.context.request.get(ME).status == 403, "CSRF refusal must not authenticate")


def test_network_error_clears_password_and_does_not_replay_registration(auth_page):
    page = auth_page
    form(page, "/register")
    email, password = identity()
    fill(page, email, password)
    requests = []

    def disconnected(route):
        requests.append(1)
        route.abort("failed")

    page.route("**" + REGISTER, disconnected)
    page.get_by_role("button", name="Зарегистрироваться", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Не удалось подтвердить результат запроса.")
    check(len(requests) == 1, "Interrupted registration must not be repeated automatically")
    check(page.get_by_label("Пароль", exact=True).input_value() == "", "Network failure must clear password")
    expect(page.get_by_role("button", name="Зарегистрироваться", exact=True)).to_be_enabled()


def test_timeout_is_safe_and_session_restore_error_is_not_a_guest(auth_page):
    page = auth_page
    form(page, "/register")
    # Exercise the client's actual abort path without waiting the production 15 seconds.
    page.evaluate("() => { const original = AbortSignal.timeout.bind(AbortSignal); AbortSignal.timeout = () => original(500) }")
    held = []
    page.route("**" + REGISTER, lambda route: held.append(route))
    email, password = identity()
    fill(page, email, password)
    page.get_by_role("button", name="Зарегистрироваться", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Не удалось подтвердить результат запроса.")
    check(len(held) == 1, "Timeout must not replay POST")
    held[0].abort()
    page.unroute("**" + REGISTER)
    page.route("**" + ME, lambda route: route.abort("failed"))
    page.goto("/session")
    expect(page.get_by_role("alert")).to_have_text("Не удалось проверить сессию. Проверьте соединение и попробуйте ещё раз.")
    expect(page).to_have_url(re.compile(r"/session$"))
    expect(page.get_by_label("Пароль", exact=True)).to_have_count(0)
    page.unroute("**" + ME)
    page.get_by_role("button", name="Проверить сессию ещё раз", exact=True).click()
    expect(page).to_have_url(re.compile(r"/login$"))


def test_expired_session_logout_and_empty_mobile_layout(auth_page):
    page = auth_page
    email, password = seed(page.context)
    check(post(page.context, LOGIN, email, password).status == 200, "Synthetic login failed")
    page.goto("/session")
    expect(page.get_by_role("button", name="Выйти", exact=True)).to_be_visible()
    check(post(page.context, "/api/v1/auth/logout/").status == 204, "Synthetic logout failed")
    page.get_by_role("button", name="Выйти", exact=True).click()
    expect(page).to_have_url(re.compile(r"/login$"))
    for size, name in (({"width": 1280, "height": 900}, "desktop"), ({"width": 375, "height": 812}, "mobile")):
        page.set_viewport_size(size)
        expect(page.get_by_label("Email", exact=True)).to_be_visible()
        expect(page.get_by_label("Пароль", exact=True)).to_be_visible()
        check(page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Auth page must fit the viewport")
        # Optional local visual review: only the empty, anonymous form is captured.
        visual = os.environ.get("QIL_AUTH_VISUAL_DIR")
        if visual:
            directory = Path(visual).resolve()
            root = Path(__file__).resolve().parents[2]
            check(directory.parent == root / ".cache" and directory.name.startswith("qil018-"), "Unsafe visual target")
            directory.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(directory / (name + ".png")), full_page=True)
    check(page.evaluate("localStorage.length === 0 && sessionStorage.length === 0"), "Auth must not persist credentials in web storage")
    check(password not in page.locator("body").inner_text(), "Password must never be rendered as text")
