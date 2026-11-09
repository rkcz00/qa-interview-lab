from django.contrib import admin
from django.http import HttpResponse
from django.urls import path
from django.views.decorators.http import require_safe


@require_safe
def index(request):
    """A static scaffold page; it does not query PostgreSQL or expose learner data."""
    return HttpResponse("QA Interview Lab backend\n", content_type="text/plain; charset=utf-8")


urlpatterns = [
    path("", index, name="index"),
    path("admin/", admin.site.urls),
]
