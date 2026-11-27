import logging
from functools import wraps

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from rest_framework.exceptions import UnsupportedMediaType, ValidationError

from apps.learning.models import Topic, TopicSection, TopicStatus
from apps.learning.serializers import language_from_query
from config.api import authentication_required, error_response, method_not_allowed, parse_json_payload, pk_from_path

from .attempts import IncompleteAnswers, build_snapshot, grade_initial_snapshot, grade_snapshot
from .completion import completion_progress
from .models import Attempt, AttemptStatus, TopicProgress
from .progress import progress_after_read, user_progress
from .reading import SectionReadRequired, public_reading, reading_snapshot, require_topic_read, save_section_read
from .progress_state import (
    ProgressWriteError, generation_from_request, progress_transaction, require_generation, reset_progress,
)
from .scoring import InvalidAnswers
from .serializers import (
    PendingAttemptSerializer,
    CompletionProgressSerializer,
    ProgressSerializer,
    ReadTopicSerializer,
    ResetProgressSerializer,
    StartAttemptSerializer,
    SubmitAttemptSerializer,
    InitialSubmitAttemptSerializer,
    SubmittedAttemptSerializer,
    TopicReadingSerializer, SectionArticleSerializer, SectionReadSerializer,
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
            except ProgressWriteError as exc:
                return error_response(exc.code, exc.message, 409)
            except SectionReadRequired as exc:
                return error_response(exc.code, exc.message, 403)
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
@progress_transaction
def start_attempt(request, topic_id):
    topics = Topic.objects.select_for_update().prefetch_related(
        "translations", "questions__translations", "questions__choices__translations",
    )
    topic = get_object_or_404(topics, pk=pk_from_path(topic_id), status=TopicStatus.PUBLISHED)
    require_generation(request, request.progress_state)
    data = _request_data(request, StartAttemptSerializer)
    require_topic_read(request.user.pk, topic.pk)
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
@progress_transaction
def submit_attempt(request, attempt_id):
    attempt = _owned_attempt(request, Attempt.objects.select_for_update(), attempt_id)
    require_generation(request, request.progress_state)
    already_submitted = attempt.status == AttemptStatus.SUBMITTED
    data = _request_data(request, SubmitAttemptSerializer if already_submitted else InitialSubmitAttemptSerializer)
    try:
        normalized, result = (grade_snapshot if already_submitted else grade_initial_snapshot)(
            attempt.content_snapshot, data["answers"],
        )
    except IncompleteAnswers:
        return error_response("incomplete_answers", "Answer every question before submitting the test.", 400)

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
@progress_transaction
def mark_article_read(request, topic_id):
    # Serialize the publication check and mark with the existing Topic editor.
    topic = get_object_or_404(
        Topic.objects.select_for_update(), pk=pk_from_path(topic_id), status=TopicStatus.PUBLISHED,
    )
    require_generation(request, request.progress_state)
    _request_data(request, ReadTopicSerializer)
    sections = list(topic.sections.filter(status=TopicStatus.PUBLISHED))
    if not sections:
        raise RuntimeError("Published topic has no sections")
    if len(sections) != 1:
        raise SectionReadRequired()
    save_section_read(request.user.pk, sections[0])
    mark = TopicProgress.objects.get(user_id=request.user.pk, topic=topic)
    return JsonResponse({"data": ProgressSerializer(progress_after_read(mark)).data})


@_learner_endpoint("GET", resource="Reading")
def topic_reading_detail(request, topic_id):
    snapshot = reading_snapshot(request.user.pk, pk_from_path(topic_id))
    payload = public_reading(snapshot, language_from_query(request.GET))
    return JsonResponse({"data": TopicReadingSerializer(payload).data})


@_learner_endpoint("GET", resource="Reading")
def section_detail(request, topic_id, section_id):
    snapshot = reading_snapshot(request.user.pk, pk_from_path(topic_id))
    section_id = pk_from_path(section_id)
    if not any(row["section_id"] == str(section_id) for row in snapshot["section_values"]):
        raise Http404
    payload = public_reading(snapshot, language_from_query(request.GET), section_id)
    return JsonResponse({"data": SectionArticleSerializer(payload).data})


@_learner_endpoint("POST", resource="Reading")
@progress_transaction
def mark_section_read(request, topic_id, section_id):
    topic = get_object_or_404(Topic.objects.select_for_update(), pk=pk_from_path(topic_id), status=TopicStatus.PUBLISHED)
    section = get_object_or_404(
        TopicSection, pk=pk_from_path(section_id), topic_id=topic.pk, status=TopicStatus.PUBLISHED,
    )
    require_generation(request, request.progress_state)
    _request_data(request, ReadTopicSerializer)
    mark = save_section_read(request.user.pk, section)
    snapshot = public_reading(reading_snapshot(request.user.pk, topic.pk), "ru")
    payload = {
        "topic_id": str(topic.pk), "section_id": str(section.pk), "read_at": mark.read_at,
        "progress_generation": snapshot["progress_generation"], "reading": snapshot["reading"],
    }
    return JsonResponse({"data": SectionReadSerializer(payload).data})


@_learner_endpoint("GET", resource="Progress")
def progress_list(request):
    _require_no_query(request)
    return JsonResponse({"data": ProgressSerializer(user_progress(request.user.pk), many=True).data})


@_learner_endpoint("GET", resource="Progress")
def completion_list(request):
    _require_no_query(request)
    payload = CompletionProgressSerializer(completion_progress(request.user.pk)).data
    return JsonResponse({"data": payload})


@_learner_endpoint("POST", resource="Progress")
@progress_transaction
def reset(request):
    generation = generation_from_request(request)
    data = _request_data(request, ResetProgressSerializer)
    generation = reset_progress(request.progress_state, generation, data["request_id"])
    return JsonResponse({"data": {"progress_generation": generation}})
