from django.http import HttpResponse
from django.urls import path
from django.views.decorators.http import require_safe


@require_safe
def index(request):
    """A static scaffold page; it does not query PostgreSQL or expose learner data."""
    return HttpResponse("QA Interview Lab backend\n", content_type="text/plain; charset=utf-8")


# Learner API and Django Admin will be connected in their own tasks.
urlpatterns = [path("", index, name="index")]
