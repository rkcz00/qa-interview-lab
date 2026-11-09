from unittest.mock import patch

from django.test import SimpleTestCase

from apps.accounts.models import User


class UserUnitTests(SimpleTestCase):
    def test_email_policy_preserves_distinct_addresses(self):
        self.assertEqual(
            User.objects.normalize_email("  QA.Engineer+Lab@Example.COM  "),
            "qa.engineer+lab@example.com",
        )
        self.assertNotEqual(
            User.objects.normalize_email("qa.engineer@example.com"),
            User.objects.normalize_email("qaengineer@example.com"),
        )
        self.assertNotEqual(
            User.objects.normalize_email("qa+lab@example.com"),
            User.objects.normalize_email("qa@example.com"),
        )

    def test_manager_hashes_password_and_defaults_to_unprivileged_user(self):
        # Only persistence is replaced; normalization and Django hashing are real.
        with patch.object(User, "save"):
            user = User.objects.create_user("  LEARNER@Example.COM ", "synthetic-test-password")
        self.assertEqual(user.email, "learner@example.com")
        self.assertNotEqual(user.password, "synthetic-test-password")
        self.assertTrue(user.check_password("synthetic-test-password"))
        self.assertFalse(user.check_password("different-test-password"))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_empty_email_is_rejected(self):
        for email in (None, "", "   "):
            with self.subTest(email=email), self.assertRaises(ValueError):
                User.objects.create_user(email)

    def test_superuser_requires_both_privilege_flags(self):
        for flags in ({"is_staff": False}, {"is_superuser": False}):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                User.objects.create_superuser("admin@example.com", **flags)

    def test_superuser_uses_email_without_username(self):
        with patch.object(User, "save"):
            user = User.objects.create_superuser(" ADMIN@Example.COM ", "synthetic-test-password")
        self.assertEqual(user.email, "admin@example.com")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertNotIn("username", {field.name for field in User._meta.fields})
