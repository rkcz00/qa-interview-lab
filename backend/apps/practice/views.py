import logging
from functools import wraps

from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from rest_framework.exceptions import UnsupportedMediaType, ValidationError

from apps.assessments.models import Attempt, AttemptStatus
from apps.assessments.reading import SectionReadRequired, require_topic_read
from apps.assessments.progress_state import ProgressWriteError, progress_transaction, require_generation
from apps.learning.models import Topic, TopicStatus
from apps.learning.serializers import language_from_query
from config.api import authentication_required, error_response, method_not_allowed, parse_json_payload, pk_from_path

from .checking import ANSWER_MAX_LENGTH, InvalidAnswer, normalize_answer, verdict_for
from .models import PracticeSubmission, PracticeTask, SubmissionStatus
from .serializers import (
    DeletePracticeSerializer, PendingPracticeSerializer, PracticePreviewSerializer,
    StartPracticeSerializer, SubmitPracticeSerializer, SubmittedPracticeSerializer,
)
from .services import build_snapshot


logger = logging.getLogger(__name__)


def practice_endpoint(method):
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
            except (InvalidAnswer, ValidationError):
                return error_response("validation_error", "Invalid practice request.", 400)
            except Exception as exc:
                logger.error("Practice request failed (%s)", type(exc).__name__)
                return error_response("internal_error", "Practice request could not be completed.", 500)
        return endpoint
    return decorate


def request_data(request, serializer_class):
    if request.GET:
        raise ValidationError("Unexpected query parameters.")
    serializer = serializer_class(data=parse_json_payload(request))
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def published_task(topic_id):
    return get_object_or_404(
        PracticeTask.objects.select_related("topic_practice__topic").prefetch_related("translations"),
        topic_practice__topic_id=topic_id, topic_practice__topic__status=TopicStatus.PUBLISHED,
        status=TopicStatus.PUBLISHED,
    )


def blocked_by(user_id, topic_id):
    reasons = []
    try:
        require_topic_read(user_id, topic_id)
    except SectionReadRequired:
        reasons.append("article_not_read")
    if not Attempt.objects.filter(user_id=user_id, topic_id=topic_id, status=AttemptStatus.SUBMITTED).exists():
        reasons.append("test_not_submitted")
    return reasons


def owned_submission(request, submission_id, *, lock=False):
    rows = PracticeSubmission.objects.select_for_update() if lock else PracticeSubmission.objects.all()
    return get_object_or_404(rows, pk=pk_from_path(submission_id), user_id=request.user.pk)


@practice_endpoint("GET")
def preview(request, topic_id):
    task = published_task(pk_from_path(topic_id))
    language = language_from_query(request.GET)
    reasons = blocked_by(request.user.pk, task.topic_practice.topic_id)
    payload = {
        "topic_id": str(task.topic_practice.topic_id), "task_id": str(task.pk),
        "practice_kind": task.topic_practice.practice_kind, "language": language,
        "title": next(row.title for row in task.translations.all() if row.language == language),
        "can_start": not reasons, "blocked_by": reasons,
        "normalization_mode": task.normalization_mode, "answer_max_length": ANSWER_MAX_LENGTH,
    }
    return JsonResponse({"data": PracticePreviewSerializer(payload).data})


@practice_endpoint("POST")
@progress_transaction
def start(request, topic_id):
    topic = get_object_or_404(Topic.objects.select_for_update(), pk=pk_from_path(topic_id), status=TopicStatus.PUBLISHED)
    task = published_task(topic.pk)
    require_generation(request, request.progress_state)
    data = request_data(request, StartPracticeSerializer)
    require_topic_read(request.user.pk, topic.pk)
    if blocked_by(request.user.pk, topic.pk):
        return error_response("practice_locked", "Read the article and submit a test first.", 403)
    submission = PracticeSubmission.objects.create(user_id=request.user.pk, task=task, task_snapshot=build_snapshot(task, topic))
    return JsonResponse({"data": PendingPracticeSerializer(submission, context={"language": data["language"]}).data}, status=201)


@practice_endpoint("GET")
def detail(request, submission_id):
    submission = owned_submission(request, submission_id)
    language = language_from_query(request.GET)
    serializer = (SubmittedPracticeSerializer(submission) if submission.status == SubmissionStatus.SUBMITTED
                  else PendingPracticeSerializer(submission, context={"language": language}))
    return JsonResponse({"data": serializer.data})


@practice_endpoint("POST")
@progress_transaction
def submit(request, submission_id):
    submission = owned_submission(request, submission_id, lock=True)
    require_generation(request, request.progress_state)
    data = request_data(request, SubmitPracticeSerializer)
    normalized = normalize_answer(data["answer_text"], submission.task_snapshot["normalization_mode"])
    if submission.status == SubmissionStatus.SUBMITTED:
        if submission.submitted_answer != normalized or submission.submitted_language != data["language"]:
            return error_response("practice_already_submitted", "This practice submission has already been submitted.", 409)
    else:
        submission.verdict = verdict_for(normalized, submission.task_snapshot["expected_answer"])
        submission.submitted_answer = normalized
        submission.submitted_language = data["language"]
        submission.submitted_at = timezone.now()
        submission.status = SubmissionStatus.SUBMITTED
        submission.save(update_fields=("status", "verdict", "submitted_answer", "submitted_language", "submitted_at"))
    return JsonResponse({"data": SubmittedPracticeSerializer(submission).data})


@practice_endpoint("POST")
@progress_transaction
def delete(request, submission_id):
    submission = owned_submission(request, submission_id, lock=True)
    require_generation(request, request.progress_state)
    request_data(request, DeletePracticeSerializer)
    submission.delete()
    return HttpResponse(status=204)
