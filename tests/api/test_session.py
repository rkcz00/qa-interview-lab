import httpx
import pytest
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session

from apps.accounts.models import User

from .test_registration import assert_error, bootstrap


LOGIN_URL = "/api/v1/auth/login/"
LOGOUT_URL = "/api/v1/auth/logout/"
ME_URL = "/api/v1/auth/me/"
TEST_EMAIL = "learner@example.invalid"
TEST_PASSWORD = "qil-synthetic-login-passphrase"


def login(client, email, token, *, password=TEST_PASSWORD):
    return client.post(
        LOGIN_URL, json={"email": email, "password": password},
        headers={"X-CSRFToken": token},
    )


def assert_account(response, user):
    assert response.status_code == 200
    if response.json() != {"data": {"user_id": str(user.pk), "email": user.email}}:
        pytest.fail("Expected only the current account's public fields", pytrace=False)


def assert_replayed_cookie_rejected(client, session_key):
    with httpx.Client(base_url=client.base_url, timeout=client.timeout, trust_env=False) as replay:
        replay.cookies.set(settings.SESSION_COOKIE_NAME, session_key, domain=client.base_url.host)
        assert_error(replay.get(ME_URL), 403, "authentication_required")


def test_anonymous_session_and_logout_are_rejected(api_client):
    assert_error(api_client.get(ME_URL), 403, "authentication_required")
    logout = api_client.post(LOGOUT_URL, json={}, headers={"X-CSRFToken": bootstrap(api_client)})
    assert_error(logout, 403, "authentication_required")
    assert not Session.objects.exists()


def test_login_rotates_anonymous_session_and_csrf(api_client):
    learner = User.objects.create_user(TEST_EMAIL, TEST_PASSWORD)
    anonymous = SessionStore()
    anonymous["qil_test_marker"] = True
    anonymous.create()
    old_key = anonymous.session_key
    api_client.cookies.set(settings.SESSION_COOKIE_NAME, old_key, domain=api_client.base_url.host)
    assert_error(api_client.get(ME_URL), 403, "authentication_required")
    old_token = bootstrap(api_client)
    old_csrf_cookie = api_client.cookies.get(settings.CSRF_COOKIE_NAME)

    response = login(api_client, " Learner@Example.INVALID ", old_token)

    assert_account(response, learner)
    new_key = api_client.cookies.get(settings.SESSION_COOKIE_NAME)
    if not new_key or new_key == old_key or Session.objects.filter(session_key=old_key).exists():
        pytest.fail("Login did not replace the anonymous session key", pytrace=False)
    session = Session.objects.get(session_key=new_key)
    if session.get_decoded().get("qil_test_marker") is not True:
        pytest.fail("Login lost the anonymous session data", pytrace=False)
    if api_client.cookies.get(settings.CSRF_COOKIE_NAME) == old_csrf_cookie:
        pytest.fail("Login did not rotate the CSRF cookie", pytrace=False)
    stale_csrf = api_client.post(LOGOUT_URL, json={}, headers={"X-CSRFToken": old_token})
    assert_error(stale_csrf, 403, "csrf_failed")
    assert_replayed_cookie_rejected(api_client, old_key)
    assert_account(api_client.get(ME_URL), learner)


def test_invalid_credentials_are_uniform_and_create_no_session(api_client):
    User.objects.create_user(TEST_EMAIL, TEST_PASSWORD)
    User.objects.create_user("inactive@example.invalid", TEST_PASSWORD, is_active=False)
    token = bootstrap(api_client)
    previous_error = None
    for email, password in (
        ("missing@example.invalid", TEST_PASSWORD),
        (TEST_EMAIL, "incorrect-synthetic-password"),
        ("inactive@example.invalid", TEST_PASSWORD),
    ):
        response = login(api_client, email, token, password=password)
        assert_error(response, 400, "invalid_credentials")
        error = response.json()
        if previous_error is not None and error != previous_error:
            pytest.fail("Invalid credential responses differed", pytrace=False)
        previous_error = error
        if settings.SESSION_COOKIE_NAME in response.cookies:
            pytest.fail("Failed login issued a session cookie", pytrace=False)
    assert not Session.objects.exists()
    assert_error(api_client.get(ME_URL), 403, "authentication_required")


@pytest.mark.parametrize("case", ["missing-cookie", "missing-header", "mismatch"])
def test_login_requires_csrf_cookie_and_matching_header(api_client, case):
    User.objects.create_user(TEST_EMAIL, TEST_PASSWORD)
    token = bootstrap(api_client)
    headers = {"X-CSRFToken": token}
    if case == "missing-cookie":
        api_client.cookies.delete(settings.CSRF_COOKIE_NAME)
    elif case == "missing-header":
        headers = {}
    else:
        headers["X-CSRFToken"] = ("A" if token[0] != "A" else "B") + token[1:]

    response = api_client.post(
        LOGIN_URL, json={"email": TEST_EMAIL, "password": TEST_PASSWORD}, headers=headers,
    )

    assert_error(response, 403, "csrf_failed")
    assert not Session.objects.exists()
    assert_error(api_client.get(ME_URL), 403, "authentication_required")


def test_login_while_authenticated_preserves_current_session(api_client):
    learner = User.objects.create_user(TEST_EMAIL, TEST_PASSWORD)
    other = User.objects.create_user("other@example.invalid", TEST_PASSWORD)
    assert_account(login(api_client, learner.email, bootstrap(api_client)), learner)
    key = api_client.cookies.get(settings.SESSION_COOKIE_NAME)
    if not key:
        pytest.fail("Login did not establish a session", pytrace=False)
    before = Session.objects.get(session_key=key)

    response = login(api_client, other.email, bootstrap(api_client))

    assert_error(response, 403, "already_authenticated")
    if settings.SESSION_COOKIE_NAME in response.cookies or api_client.cookies.get(settings.SESSION_COOKIE_NAME) != key:
        pytest.fail("Repeated login changed the session cookie", pytrace=False)
    after = Session.objects.get(session_key=key)
    if after.session_data != before.session_data or after.expire_date != before.expire_date:
        pytest.fail("Repeated login changed stored session data", pytrace=False)
    assert_account(api_client.get(ME_URL), learner)


def test_staff_logout_revokes_session_and_replay(api_client):
    staff = User.objects.create_user("staff@example.invalid", TEST_PASSWORD, is_staff=True)
    assert_account(login(api_client, staff.email, bootstrap(api_client)), staff)
    old_key = api_client.cookies.get(settings.SESSION_COOKIE_NAME)
    if not old_key:
        pytest.fail("Login did not establish the staff session", pytrace=False)
    assert_error(api_client.post(LOGOUT_URL, json={}), 403, "csrf_failed")
    assert_account(api_client.get(ME_URL), staff)

    logout = api_client.post(LOGOUT_URL, json={}, headers={"X-CSRFToken": bootstrap(api_client)})

    assert logout.status_code == 204
    if logout.content or Session.objects.filter(session_key=old_key).exists():
        pytest.fail("Logout returned a body or left the session active", pytrace=False)
    if settings.SESSION_COOKIE_NAME in api_client.cookies:
        pytest.fail("Logout did not clear the session cookie", pytrace=False)
    assert_error(api_client.get(ME_URL), 403, "authentication_required")
    assert_replayed_cookie_rejected(api_client, old_key)
