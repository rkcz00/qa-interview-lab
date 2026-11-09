from unittest.mock import patch

from django.conf import settings
from django.contrib.sessions.models import Session
from django.test import Client, SimpleTestCase, TestCase

from apps.accounts.models import User


CSRF_URL = "/api/v1/auth/csrf/"
LOGIN_URL = "/api/v1/auth/login/"
LOGOUT_URL = "/api/v1/auth/logout/"
ME_URL = "/api/v1/auth/me/"
TEST_EMAIL = "learner@example.invalid"
TEST_PASSWORD = "qil-synthetic-login-passphrase"


def csrf_header(client):
    return {"X-CSRFToken": client.get(CSRF_URL).json()["data"]["csrf_token"]}


class SessionRequestTests(SimpleTestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_guest_session_and_logout_require_authentication(self):
        me = self.client.get(ME_URL)
        self.assertEqual(me.status_code, 403)
        self.assertEqual(me.json()["error"]["code"], "authentication_required")

        without_csrf = self.client.post(LOGOUT_URL, {}, content_type="application/json")
        self.assertEqual(without_csrf.status_code, 403)
        self.assertEqual(without_csrf.json()["error"]["code"], "csrf_failed")

        logout = self.client.post(
            LOGOUT_URL, {}, content_type="application/json", headers=csrf_header(self.client),
        )
        self.assertEqual(logout.status_code, 403)
        self.assertEqual(logout.json()["error"]["code"], "authentication_required")

    def test_login_validates_protocol_before_authenticating(self):
        headers = csrf_header(self.client)
        with patch("apps.accounts.views.authenticate") as authenticate:
            for response, status, code in (
                (self.client.get(LOGIN_URL), 405, "method_not_allowed"),
                (self.client.post(LOGIN_URL, "{}", content_type="text/plain", headers=headers),
                 415, "unsupported_media_type"),
                (self.client.post(LOGIN_URL, "{", content_type="application/json", headers=headers),
                 400, "validation_error"),
                (self.client.post(
                    LOGIN_URL, {"email": TEST_EMAIL, "password": 1234},
                    content_type="application/json", headers=headers,
                ), 400, "validation_error"),
            ):
                with self.subTest(code=code):
                    self.assertEqual(response.status_code, status)
                    self.assertEqual(response.json()["error"]["code"], code)
            authenticate.assert_not_called()

    def test_invalid_credentials_do_not_log_the_user_in(self):
        with patch("apps.accounts.views.authenticate", return_value=None), patch(
            "apps.accounts.views.django_login"
        ) as login:
            response = self.client.post(
                LOGIN_URL, {"email": TEST_EMAIL, "password": TEST_PASSWORD},
                content_type="application/json", headers=csrf_header(self.client),
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_credentials")
        self.assertFalse(settings.SESSION_COOKIE_NAME in response.cookies)
        login.assert_not_called()

    def test_logout_rejects_nonempty_json_before_changing_session(self):
        user = User(id=1, email=TEST_EMAIL)
        with patch("django.contrib.auth.middleware.get_user", return_value=user), patch(
            "apps.accounts.views.django_logout"
        ) as logout:
            response = self.client.post(
                LOGOUT_URL, {"next": "/"}, content_type="application/json",
                headers=csrf_header(self.client),
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "validation_error")
        logout.assert_not_called()


class SessionDatabaseTests(TestCase):
    def test_logout_invalidates_only_the_requesting_session(self):
        first = Client(enforce_csrf_checks=True)
        second = Client(enforce_csrf_checks=True)
        first.force_login(User.objects.create_user(TEST_EMAIL))
        other_user = User.objects.create_user("other@example.invalid")
        second.force_login(other_user)
        first_key = first.cookies[settings.SESSION_COOKIE_NAME].value

        response = first.post(
            LOGOUT_URL, {}, content_type="application/json", headers=csrf_header(first),
        )

        self.assertEqual(response.status_code, 204)
        self.assertTrue(response.content == b"")
        self.assertFalse(Session.objects.filter(session_key=first_key).exists())
        self.assertEqual(first.get(ME_URL).status_code, 403)
        current = second.get(ME_URL)
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["data"]["user_id"], str(other_user.pk))
