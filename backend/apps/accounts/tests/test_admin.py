from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User


TEST_PASSWORD = "qil-synthetic-test-passphrase"


class AdminLoginPageTests(SimpleTestCase):
    def test_admin_login_uses_email_and_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        login_url = reverse("admin:login")
        page = client.get(login_url)

        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["form"].username_field.name, "email")
        response = client.post(
            login_url,
            {"username": "admin@example.invalid", "password": TEST_PASSWORD},
        )
        self.assertEqual(response.status_code, 403)


class EmailUserAdminTests(TestCase):
    def test_createsuperuser_can_log_in_to_admin_by_email(self):
        with patch.dict("os.environ", {"DJANGO_SUPERUSER_PASSWORD": TEST_PASSWORD}):
            call_command(
                "createsuperuser",
                interactive=False,
                email="ADMIN+Lab@Example.INVALID",
                stdout=StringIO(),
            )
        user = User.objects.get(email="admin+lab@example.invalid")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertNotEqual(user.password, TEST_PASSWORD)
        self.assertTrue(user.check_password(TEST_PASSWORD))

        users_url = reverse("admin:accounts_user_changelist")
        response = self.client.post(
            reverse("admin:login"),
            {
                "username": " ADMIN+LAB@EXAMPLE.INVALID ",
                "password": TEST_PASSWORD,
                "next": users_url,
            },
        )
        self.assertRedirects(response, users_url)

    def test_admin_can_add_and_open_an_email_user(self):
        admin = User.objects.create_superuser("admin@example.invalid", TEST_PASSWORD)
        self.client.force_login(admin)
        add_url = reverse("admin:accounts_user_add")
        new_user = {
            "email": " Learner@Example.INVALID ",
            "usable_password": "true",
            "password1": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        }

        response = self.client.post(add_url, new_user)
        learner = User.objects.get(email="learner@example.invalid")
        change_url = reverse("admin:accounts_user_change", args=[learner.pk])
        self.assertRedirects(response, change_url, fetch_redirect_response=False)
        self.assertTrue(learner.check_password(TEST_PASSWORD))
        self.assertFalse(learner.is_staff)
        self.assertFalse(learner.is_superuser)

        change_page = self.client.get(change_url)
        self.assertEqual(change_page.status_code, 200)
        self.assertIn("email", change_page.context["adminform"].form.fields)
        self.assertNotIn("username", change_page.context["adminform"].form.fields)

        duplicate = self.client.post(add_url, {**new_user, "email": "LEARNER@example.invalid"})
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.context["adminform"].form.errors)
        self.assertEqual(User.objects.filter(email=learner.email).count(), 1)

    def test_learner_is_redirected_to_admin_login(self):
        learner = User.objects.create_user("learner@example.invalid")
        self.client.force_login(learner)
        users_url = reverse("admin:accounts_user_changelist")
        response = self.client.get(users_url)

        self.assertRedirects(
            response,
            f"{reverse('admin:login')}?next={users_url}",
            fetch_redirect_response=False,
        )

    def test_staff_without_user_permissions_cannot_open_user_admin(self):
        staff = User.objects.create_user("staff@example.invalid", is_staff=True)
        learner = User.objects.create_user("learner@example.invalid")
        self.client.force_login(staff)

        for url in (
            reverse("admin:accounts_user_changelist"),
            reverse("admin:accounts_user_change", args=[learner.pk]),
            reverse("admin:accounts_user_add"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
