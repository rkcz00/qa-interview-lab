from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower, Trim

from .managers import UserManager


class User(AbstractUser):
    username = None
    email = models.EmailField("email", unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(
                Lower(Trim("email")),
                name="accounts_user_email_canonical_unique",
            ),
        ]

    def clean(self):
        super().clean()
        self.email = UserManager.normalize_email(self.email)

    def save(self, *args, **kwargs):
        self.email = UserManager.normalize_email(self.email)
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.email
