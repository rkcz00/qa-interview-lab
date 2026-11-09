from django.contrib.auth import authenticate
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.models import User


class UserDatabaseTests(TestCase):
    """Integration checks must run on a separate PostgreSQL test database."""

    def test_email_login_is_case_insensitive_and_strips_outer_spaces(self):
        user = User.objects.create_user(" LEARNER@Example.COM ", "synthetic-test-password")
        authenticated = authenticate(email=" Learner@EXAMPLE.com ", password="synthetic-test-password")
        self.assertEqual(authenticated, user)
        user.refresh_from_db()
        self.assertEqual(user.email, "learner@example.com")

    def test_database_rejects_duplicates_even_when_save_is_bypassed(self):
        User.objects.create_user("learner@example.com", "synthetic-test-password")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([User(email=" LEARNER@EXAMPLE.COM ")])
        self.assertEqual(User.objects.count(), 1)
