from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.conf import settings
from django.db import connections
from django.test import Client, SimpleTestCase, TransactionTestCase

from apps.accounts.models import User
from apps.accounts.serializers import RegistrationSerializer


CSRF_URL = "/api/v1/auth/csrf/"
REGISTER_URL = "/api/v1/auth/register/"
TEST_PASSWORD = "qil-synthetic-registration-passphrase"
TEST_EMAIL = "learner@example.invalid"


class RegistrationSerializerTests(SimpleTestCase):
    def test_normalizes_email_and_preserves_password_whitespace(self):
        password = f" {TEST_PASSWORD} "
        serializer = RegistrationSerializer(data={
            "email": " Learner+Lab@Example.INVALID ",
            "password": password,
        })
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["email"], "learner+lab@example.invalid")
        self.assertTrue(serializer.validated_data["password"] == password)

    def test_rejects_invalid_types_fields_and_passwords(self):
        valid = {"email": TEST_EMAIL, "password": TEST_PASSWORD}
        for label, payload in (
            ("array", [valid]),
            ("missing password", {"email": TEST_EMAIL}),
            ("unknown field", {**valid, "is_staff": True}),
            ("numeric value", {**valid, "password": 123456789}),
            ("invalid email", {**valid, "email": "not-an-email"}),
            ("short password", {**valid, "password": "abc"}),
            ("common password", {**valid, "password": "password"}),
        ):
            with self.subTest(case=label):
                self.assertFalse(RegistrationSerializer(data=payload).is_valid())


class RegistrationRequestTests(SimpleTestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_bootstrap_cookie_and_csrf_rejection_without_header(self):
        bootstrap = self.client.get(CSRF_URL)
        self.assertEqual(bootstrap.status_code, 200)
        self.assertTrue(bool(bootstrap.json()["data"]["csrf_token"]))
        self.assertTrue(settings.CSRF_COOKIE_NAME in bootstrap.cookies)
        self.assertFalse(settings.SESSION_COOKIE_NAME in bootstrap.cookies)
        self.assertIn("no-store", bootstrap.headers["Cache-Control"])

        response = self.client.post(
            REGISTER_URL, {"email": TEST_EMAIL, "password": TEST_PASSWORD},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "csrf_failed")

    def test_method_media_type_and_malformed_json_errors(self):
        token = self.client.get(CSRF_URL).json()["data"]["csrf_token"]
        headers = {"X-CSRFToken": token}
        for response, status, code in (
            (self.client.get(REGISTER_URL), 405, "method_not_allowed"),
            (
                self.client.post(REGISTER_URL, "email=value", content_type="text/plain", headers=headers),
                415,
                "unsupported_media_type",
            ),
            (
                self.client.post(REGISTER_URL, "{", content_type="application/json", headers=headers),
                400,
                "validation_error",
            ),
        ):
            with self.subTest(code=code):
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code)

    def test_numeric_password_returns_validation_error_without_saving(self):
        token = self.client.get(CSRF_URL).json()["data"]["csrf_token"]
        with patch.object(RegistrationSerializer, "save") as save:
            response = self.client.post(
                REGISTER_URL, {"email": TEST_EMAIL, "password": 123456789},
                content_type="application/json", headers={"X-CSRFToken": token},
            )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json() == {
            "error": {"code": "validation_error", "message": "Invalid registration data."},
        })
        save.assert_not_called()

    def test_unexpected_error_uses_safe_json_message(self):
        token = self.client.get(CSRF_URL).json()["data"]["csrf_token"]
        with patch.object(RegistrationSerializer, "save", side_effect=RuntimeError("synthetic detail")):
            response = self.client.post(
                REGISTER_URL, {"email": TEST_EMAIL, "password": TEST_PASSWORD},
                content_type="application/json", headers={"X-CSRFToken": token},
            )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "internal_error")
        self.assertFalse(b"synthetic detail" in response.content)


class ConcurrentRegistrationTests(TransactionTestCase):
    def test_concurrent_normalized_email_registrations_create_one_user(self):
        start = Barrier(2)

        def register(email):
            try:
                client = Client(enforce_csrf_checks=True)
                token = client.get(CSRF_URL).json()["data"]["csrf_token"]
                start.wait(timeout=10)
                response = client.post(
                    REGISTER_URL, {"email": email, "password": TEST_PASSWORD},
                    content_type="application/json", headers={"X-CSRFToken": token},
                )
                return response.status_code, response.json().get("error", {}).get("code")
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(register, (" Learner@Example.INVALID ", TEST_EMAIL)))
        self.assertCountEqual(results, [(201, None), (400, "validation_error")])
        self.assertEqual(User.objects.filter(email=TEST_EMAIL).count(), 1)
