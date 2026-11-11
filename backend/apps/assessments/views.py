import logging
from functools import wraps

from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from rest_framework.exceptions import UnsupportedMediaType, ValidationError

from apps.learning.models import Topic, TopicStatus
from apps.learning.serializers import language_from_query
from config.api import authentication_required, error_response, method_not_allowed, parse_json_payload, pk_from_path

from .attempts import build_snapshot, grade_snapshot
from .models import Attempt, AttemptStatus, TopicProgress
from .progress import progress_after_read, user_progress
from .scoring import InvalidAnswers
from .serializers import (
    PendingAttemptSerializer,
    ProgressSerializer,
    ReadTopicSerializer,
    StartAttemptSerializer,
    SubmitAttemptSerializer,
    SubmittedAttemptSerializer,
)


logger = logging.getLogger(__name__)


def _learner_endpoint(method, *, resource="Attempt"):
    def decorate(view):
        @wraps(view)
        @never_cache
        def endpoint(request, *args, **kwargs):
            if request.method != method:
                return method_not_allowed(method)
            try:
                if not request.user.is_authenticated:
                    return authentication_required()
                return view(request, *args, **kwargs)
            except Http404:
                return error_response("not_found", "Requested resource not found.", 404)
            except UnsupportedMediaType:
                return error_response("unsupported_media_type", "Expected application/json.", 415)
            except (InvalidAnswers, ValidationError):
                return error_response("validation_error", f"Invalid {resource.lower()} request.", 400)
            except Exception as exc:
                logger.error("%s request failed (%s)", resource, type(exc).__name__)
                return error_response("internal_error", f"{resource} request could not be completed.", 500)

        return endpoint

    return decorate


def _require_no_query(request):
    if request.GET:
        raise ValidationError("Unexpected query parameters.")


def _request_data(request, serializer_class):
    _require_no_query(request)
    serializer = serializer_class(data=parse_json_payload(request))
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _owned_attempt(request, queryset, attempt_id):
    return get_object_or_404(queryset, pk=pk_from_path(attempt_id), user_id=request.user.pk)


@_learner_endpoint("POST")
@transaction.atomic
def start_attempt(request, topic_id):
    topics = Topic.objects.select_for_update().prefetch_related(
        "translations", "questions__translations", "questions__choices__translations",
    )
    topic = get_object_or_404(topics, pk=pk_from_path(topic_id), status=TopicStatus.PUBLISHED)
    data = _request_data(request, StartAttemptSerializer)
    attempt = Attempt.objects.create(user_id=request.user.pk, topic=topic, content_snapshot=build_snapshot(topic))
    payload = PendingAttemptSerializer(attempt, context={"language": data["language"]}).data
    return JsonResponse({"data": payload}, status=201)


@_learner_endpoint("GET")
def attempt_detail(request, attempt_id):
    attempt = _owned_attempt(request, Attempt.objects.all(), attempt_id)
    language = language_from_query(request.GET)
    if attempt.status == AttemptStatus.SUBMITTED:
        payload = SubmittedAttemptSerializer(attempt).data
    else:
        payload = PendingAttemptSerializer(attempt, context={"language": language}).data
    return JsonResponse({"data": payload})


@_learner_endpoint("POST")
@transaction.atomic
def submit_attempt(request, attempt_id):
    attempt = _owned_attempt(request, Attempt.objects.select_for_update(), attempt_id)
    data = _request_data(request, SubmitAttemptSerializer)
    normalized, result = grade_snapshot(attempt.content_snapshot, data["answers"])

    if attempt.status == AttemptStatus.SUBMITTED:
        if attempt.submitted_language != data["language"] or attempt.submitted_answers != normalized:
            return error_response("attempt_already_submitted", "This attempt has already been submitted.", 409)
    else:
        attempt.status = AttemptStatus.SUBMITTED
        attempt.submitted_at = timezone.now()
        attempt.submitted_language = data["language"]
        attempt.submitted_answers = normalized
        attempt.correct_count = result["correct_count"]
        attempt.total_count = result["total_count"]
        attempt.save(update_fields=(
            "status", "submitted_at", "submitted_language", "submitted_answers", "correct_count", "total_count",
        ))

    return JsonResponse({"data": SubmittedAttemptSerializer(attempt).data})


@_learner_endpoint("GET")
def attempt_history(request):
    _require_no_query(request)
    attempts = (
        Attempt.objects.filter(user_id=request.user.pk, status=AttemptStatus.SUBMITTED)
        .only("topic_id", "status", "submitted_language", "submitted_at", "content_snapshot", "correct_count", "total_count")
        .order_by("-submitted_at", "-pk")
    )
    return JsonResponse({"data": SubmittedAttemptSerializer(attempts, many=True).data})


@_learner_endpoint("POST", resource="Progress")
@transaction.atomic
def mark_article_read(request, topic_id):
    # Serialize the publication check and mark with the existing Topic editor.
    topic = get_object_or_404(
        Topic.objects.select_for_update(), pk=pk_from_path(topic_id), status=TopicStatus.PUBLISHED,
    )
    _request_data(request, ReadTopicSerializer)
    mark, _ = TopicProgress.objects.get_or_create(user_id=request.user.pk, topic=topic)
    return JsonResponse({"data": ProgressSerializer(progress_after_read(mark)).data})


@_learner_endpoint("GET", resource="Progress")
def progress_list(request):
    _require_no_query(request)
    return JsonResponse({"data": ProgressSerializer(user_progress(request.user.pk), many=True).data})
