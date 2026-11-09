import logging
from io import BytesIO

from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from django.http.request import UnreadablePostError
from django.middleware.csrf import get_token
from django.views.csrf import csrf_failure as django_csrf_failure
from django.views.decorators.cache import never_cache
from rest_framework.exceptions import ParseError, ValidationError
from rest_framework.parsers import JSONParser

from .serializers import RegistrationSerializer


logger = logging.getLogger(__name__)


def _error(code, message, status, *, headers=None):
    return JsonResponse({"error": {"code": code, "message": message}}, status=status, headers=headers)


def _method_not_allowed(method):
    return _error("method_not_allowed", "Method not allowed.", 405, headers={"Allow": method})


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

    return JsonResponse({"data": {"user_id": str(user.pk), "email": user.email}}, status=201)
