from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError, transaction
from django.db.models import Value
from django.db.models.functions import Lower, Trim
from psycopg.errors import UniqueViolation
from rest_framework import serializers
from rest_framework.settings import api_settings

from .models import User


def _has_credentials(data):
    return (
        isinstance(data, dict)
        and data.keys() == {"email", "password"}
        and all(isinstance(value, str) for value in data.values())
    )


class RegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=User._meta.get_field("email").max_length)
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def to_internal_value(self, data):
        if not _has_credentials(data):
            raise serializers.ValidationError("Expected email and password strings.")
        return super().to_internal_value({
            "email": User.objects.normalize_email(data["email"]),
            "password": data["password"],
        })

    def validate(self, attrs):
        validate_password(attrs["password"], user=User(email=attrs["email"]))
        return attrs

    def create(self, validated_data):
        try:
            with transaction.atomic():
                return User.objects.create_user(**validated_data)
        except IntegrityError as exc:
            if not isinstance(exc.__cause__, UniqueViolation):
                raise
            email_key = Lower(Trim(Value(validated_data["email"])))
            if User.objects.alias(email_key=Lower(Trim("email"))).filter(email_key=email_key).exists():
                raise serializers.ValidationError("Email is already registered.") from None
            raise


class LoginSerializer(serializers.Serializer):
    email = serializers.CharField(allow_blank=True, trim_whitespace=False)
    password = serializers.CharField(allow_blank=True, trim_whitespace=False, write_only=True)

    def to_internal_value(self, data):
        if not _has_credentials(data):
            raise serializers.ValidationError({
                api_settings.NON_FIELD_ERRORS_KEY: ["Expected email and password strings."],
            })
        return super().to_internal_value(data)
