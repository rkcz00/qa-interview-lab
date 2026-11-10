import logging
from io import BytesIO

from django.contrib.auth import authenticate
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.core.exceptions import RequestDataTooBig
from django.http import HttpResponse, JsonResponse
from django.http.request import UnreadablePostError
from django.middleware.csrf import get_token
from django.views.csrf import csrf_failure as django_csrf_failure
from django.views.decorators.cache import never_cache
from rest_framework.exceptions import ParseError, UnsupportedMediaType, ValidationError
from rest_framework.parsers import JSONParser

from config.api import authentication_required as _authentication_required
from config.api import error_response as _error
from config.api import method_not_allowed as _method_not_allowed

from .serializers import LoginSerializer, RegistrationSerializer


logger = logging.getLogger(__name__)


def _account_response(user, *, status=200):
    return JsonResponse({"data": {"user_id": str(user.pk), "email": user.email}}, status=status)


def _session_payload(request):
    if request.content_type != "application/json":
        raise UnsupportedMediaType(request.content_type)
    try:
        return JSONParser().parse(BytesIO(request.body))
    except (ParseError, RequestDataTooBig, UnreadablePostError, RecursionError):
        raise ValidationError("Invalid JSON data.") from None


def _session_error(exc):
    if isinstance(exc, UnsupportedMediaType):
        return _error("unsupported_media_type", "Expected application/json.", 415)
    if isinstance(exc, ValidationError):
        return _error("validation_error", "Invalid request data.", 400)
    logger.error("Session request failed (%s)", type(exc).__name__)
    return _error("internal_error", "Session request could not be completed.", 500)


def csrf_failure(request, reason=""):
    if request.path_info.startswith("/api/v1/"):
        return _error("csrf_failed", "CSRF verification failed.", 403)
    return django_csrf_failure(request, reason=reason)


@never_cache
def csrf_bootstrap(request):
    if request.method != "GET":
        return _method_not_allowed("GET")
    return JsonResponse({"data": {"csrf_token": get_token(request)}})


def register(request):
    if request.method != "POST":
        return _method_not_allowed("POST")
    try:
        if request.user.is_authenticated:
            return _error("already_authenticated", "You are already signed in.", 403)
        if request.content_type != "application/json":
            return _error("unsupported_media_type", "Expected application/json.", 415)

        payload = JSONParser().parse(BytesIO(request.body))
        serializer = RegistrationSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
    except (ParseError, RequestDataTooBig, UnreadablePostError, RecursionError, ValidationError):
        return _error("validation_error", "Invalid registration data.", 400)
    except Exception as exc:
        logger.error("Account registration failed (%s)", type(exc).__name__)
        return _error("internal_error", "Registration could not be completed.", 500)

    return _account_response(user, status=201)


def login(request):
    if request.method != "POST":
        return _method_not_allowed("POST")
    try:
        if request.user.is_authenticated:
            return _error("already_authenticated", "You are already signed in.", 403)
        serializer = LoginSerializer(data=_session_payload(request))
        serializer.is_valid(raise_exception=True)
        user = authenticate(request, **serializer.validated_data)
        if user is None:
            return _error("invalid_credentials", "Invalid email or password.", 400)
        django_login(request, user)
    except Exception as exc:
        return _session_error(exc)
    return _account_response(user)


@never_cache
def current_session(request):
    if request.method != "GET":
        return _method_not_allowed("GET")
    try:
        user = request.user
        if not user.is_authenticated:
            return _authentication_required()
        return _account_response(user)
    except Exception as exc:
        return _session_error(exc)


def logout(request):
    if request.method != "POST":
        return _method_not_allowed("POST")
    try:
        if not request.user.is_authenticated:
            return _authentication_required()
        if _session_payload(request) != {}:
            raise ValidationError("Expected an empty JSON object.")
        django_logout(request)
    except Exception as exc:
        return _session_error(exc)
    return HttpResponse(status=204)
