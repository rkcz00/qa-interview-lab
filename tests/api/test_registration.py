import pytest
from django.conf import settings
from django.contrib.sessions.models import Session

from apps.accounts.models import User


CSRF_URL = "/api/v1/auth/csrf/"
REGISTER_URL = "/api/v1/auth/register/"
TEST_EMAIL = "learner@example.invalid"
TEST_PASSWORD = "qil-synthetic-registration-passphrase"


def bootstrap(client):
    response = client.get(CSRF_URL)
    assert response.status_code == 200
    payload = response.json()
    if set(payload) != {"data"} or set(payload["data"]) != {"csrf_token"}:
        pytest.fail("Unexpected fields in CSRF bootstrap response", pytrace=False)
    token = payload["data"]["csrf_token"]
    if not isinstance(token, str) or not token or settings.CSRF_COOKIE_NAME not in response.cookies:
        pytest.fail("Missing CSRF token or cookie", pytrace=False)
    if settings.SESSION_COOKIE_NAME in response.cookies:
        pytest.fail("CSRF bootstrap issued a session cookie", pytrace=False)
    assert "no-store" in response.headers["Cache-Control"]
    assert "Cookie" in response.headers["Vary"]
    return token


def assert_error(response, status, code):
    assert response.status_code == status
    payload = response.json()
    if set(payload) != {"error"} or set(payload["error"]) != {"code", "message"}:
        pytest.fail("Unexpected fields in error response", pytrace=False)
    if payload["error"]["code"] != code or not isinstance(payload["error"]["message"], str):
        pytest.fail(f"Expected {code} and an error message string", pytrace=False)


def test_registers_with_csrf_and_returns_only_public_account(api_client):
    session_count = Session.objects.count()
    token = bootstrap(api_client)
    response = api_client.post(
        REGISTER_URL, json={"email": " Learner@Example.INVALID ", "password": TEST_PASSWORD},
        headers={"X-CSRFToken": token},
    )

    assert response.status_code == 201
    user = User.objects.get(email=TEST_EMAIL)
    if response.json() != {"data": {"user_id": str(user.pk), "email": TEST_EMAIL}}:
        pytest.fail("Registration response must contain only the public account", pytrace=False)
    if user.password == TEST_PASSWORD or not user.check_password(TEST_PASSWORD):
        pytest.fail("Stored password did not pass the Django hash check", pytrace=False)
    if settings.SESSION_COOKIE_NAME in api_client.cookies or Session.objects.count() != session_count:
        pytest.fail("Registration established a session", pytrace=False)


@pytest.mark.parametrize("case", ["missing-cookie", "missing-header", "mismatch"])
def test_csrf_failure_does_not_create_an_account(api_client, case):
    token = bootstrap(api_client)
    headers = {"X-CSRFToken": token}
    if case == "missing-cookie":
        api_client.cookies.delete(settings.CSRF_COOKIE_NAME)
    elif case == "missing-header":
        headers = {}
    else:
        headers["X-CSRFToken"] = ("A" if token[0] != "A" else "B") + token[1:]

    response = api_client.post(
        REGISTER_URL, json={"email": TEST_EMAIL, "password": TEST_PASSWORD}, headers=headers,
    )
    assert_error(response, 403, "csrf_failed")
    assert not User.objects.filter(email=TEST_EMAIL).exists()


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("not-an-email", TEST_PASSWORD),
        (TEST_EMAIL, "abc"),
        (TEST_EMAIL, 123456789),
        (TEST_EMAIL, None),
        (TEST_EMAIL, ["abc"]),
        (TEST_EMAIL, {"value": "abc"}),
    ],
    ids=[
        "invalid-email", "weak-password", "numeric-password",
        "null-password", "array-password", "object-password",
    ],
)
def test_invalid_registration_does_not_create_an_account(api_client, email, password):
    count = User.objects.count()
    response = api_client.post(
        REGISTER_URL, json={"email": email, "password": password},
        headers={"X-CSRFToken": bootstrap(api_client)},
    )
    assert_error(response, 400, "validation_error")
    assert User.objects.count() == count


def test_rejects_duplicate_normalized_email(api_client):
    # bulk_create bypasses model normalization, as with legacy rows.
    User.objects.bulk_create([User(email=" LEARNER@Example.INVALID ")])
    response = api_client.post(
        REGISTER_URL, json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        headers={"X-CSRFToken": bootstrap(api_client)},
    )
    assert_error(response, 400, "validation_error")
    assert User.objects.count() == 1


def test_authenticated_registration_preserves_existing_session(api_client):
    admin = User.objects.create_superuser("admin@example.invalid", TEST_PASSWORD)
    login = api_client.post(
        "/admin/login/", data={"username": admin.email, "password": TEST_PASSWORD, "next": "/admin/"},
        headers={"X-CSRFToken": bootstrap(api_client)},
    )
    assert login.status_code == 302
    session_key = api_client.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_key:
        pytest.fail("Admin login did not establish the test session", pytrace=False)
    before = Session.objects.get(session_key=session_key)

    response = api_client.post(
        REGISTER_URL, json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        headers={"X-CSRFToken": bootstrap(api_client)},
    )

    assert_error(response, 403, "already_authenticated")
    assert not User.objects.filter(email=TEST_EMAIL).exists()
    if (
        settings.SESSION_COOKIE_NAME in response.cookies
        or api_client.cookies.get(settings.SESSION_COOKIE_NAME) != session_key
    ):
        pytest.fail("Registration changed the session cookie", pytrace=False)
    after = Session.objects.get(session_key=session_key)
    if after.session_data != before.session_data or after.expire_date != before.expire_date:
        pytest.fail("Registration changed the stored session", pytrace=False)
    assert api_client.get("/admin/").status_code == 200
