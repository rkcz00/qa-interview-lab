"""Serialize learner progress writes before any Topic/work locks are acquired."""

from contextlib import contextmanager
from functools import wraps
import re

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import Http404
from rest_framework.exceptions import ValidationError

from .models import Attempt, TopicProgress, UserProgressState


MAX_GENERATION = 2**63 - 1


class ProgressWriteError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def generation_from_request(request):
    value = request.headers.get("X-Progress-Generation", "")
    if not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > MAX_GENERATION:
        raise ValidationError("Invalid progress generation.")
    return int(value)


def require_generation(request, state):
    generation = generation_from_request(request)
    if generation != state.generation:
        raise ProgressWriteError("progress_reset", "Progress has been reset. Check the current state.")
    return generation


@contextmanager
def progress_write(user_id):
    with transaction.atomic():
        # The existing User row is also the mutex when the state row does not exist yet.
        user_model = get_user_model()
        try:
            user_model.objects.select_for_update().only("pk").get(pk=user_id)
        except user_model.DoesNotExist:
            raise Http404 from None
        state = UserProgressState.objects.filter(user_id=user_id).first()
        if state is None:
            # Do not persist operational state for a rejected request or from GET.
            state = UserProgressState(user_id=user_id)
        yield state


def progress_transaction(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        with progress_write(request.user.pk) as state:
            request.progress_state = state
            return view(request, *args, **kwargs)
    return wrapped


def reset_progress(state, generation, request_id):
    """Called only inside progress_write; keep response construction in that transaction."""
    if state.last_reset_request_id == request_id:
        if state.last_reset_from_generation == generation:
            return str(state.generation)
        raise ProgressWriteError("reset_request_conflict", "This reset request used a different generation.")
    if generation != state.generation:
        raise ProgressWriteError("progress_reset", "Progress has been reset. Check the current state.")
    if state.generation == MAX_GENERATION:
        raise OverflowError("Progress generation exhausted")

    from apps.practice.models import PracticeSubmission

    TopicProgress.objects.filter(user_id=state.user_id).delete()
    Attempt.objects.filter(user_id=state.user_id).delete()
    PracticeSubmission.objects.filter(user_id=state.user_id).delete()
    state.last_reset_request_id = request_id
    state.last_reset_from_generation = generation
    state.generation += 1
    state.save()
    return str(state.generation)
