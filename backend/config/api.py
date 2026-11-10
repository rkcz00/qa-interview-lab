from io import BytesIO

from django.core.exceptions import RequestDataTooBig
from django.http import Http404, JsonResponse
from django.http.request import UnreadablePostError
from rest_framework.exceptions import ParseError, UnsupportedMediaType, ValidationError
from rest_framework.parsers import JSONParser


def error_response(code, message, status, *, headers=None):
    return JsonResponse({"error": {"code": code, "message": message}}, status=status, headers=headers)


def method_not_allowed(method):
    return error_response("method_not_allowed", "Method not allowed.", 405, headers={"Allow": method})


def authentication_required():
    return error_response("authentication_required", "Authentication is required.", 403)


def parse_json_payload(request):
    if request.content_type != "application/json":
        raise UnsupportedMediaType(request.content_type)
    try:
        return JSONParser().parse(BytesIO(request.body))
    except (ParseError, RequestDataTooBig, UnreadablePostError, RecursionError):
        raise ValidationError("Invalid JSON data.") from None


def pk_from_path(identifier):
    if len(identifier) > 19 or not identifier.isascii() or not identifier.isdecimal():
        raise Http404
    pk = int(identifier)
    if str(pk) != identifier or not 1 <= pk <= 2**63 - 1:
        raise Http404
    return pk
