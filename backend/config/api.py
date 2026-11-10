from django.http import JsonResponse


def error_response(code, message, status, *, headers=None):
    return JsonResponse({"error": {"code": code, "message": message}}, status=status, headers=headers)


def method_not_allowed(method):
    return error_response("method_not_allowed", "Method not allowed.", 405, headers={"Allow": method})


def authentication_required():
    return error_response("authentication_required", "Authentication is required.", 403)
