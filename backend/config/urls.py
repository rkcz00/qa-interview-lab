from django.contrib import admin
from django.http import HttpResponse
from django.urls import path
from django.views.decorators.http import require_safe

from apps.accounts import views as accounts_views
from apps.assessments import views as assessments_views
from apps.learning import views as learning_views


@require_safe
def index(request):
    """A static scaffold page; it does not query PostgreSQL or expose learner data."""
    return HttpResponse("QA Interview Lab backend\n", content_type="text/plain; charset=utf-8")


urlpatterns = [
    path("", index, name="index"),
    path("admin/", admin.site.urls),
    path("api/v1/auth/csrf/", accounts_views.csrf_bootstrap, name="auth-csrf"),
    path("api/v1/auth/register/", accounts_views.register, name="auth-register"),
    path("api/v1/auth/login/", accounts_views.login, name="auth-login"),
    path("api/v1/auth/logout/", accounts_views.logout, name="auth-logout"),
    path("api/v1/auth/me/", accounts_views.current_session, name="auth-me"),
    path("api/v1/topics/", learning_views.topic_catalog, name="topic-catalog"),
    path("api/v1/topics/<str:topic_id>/", learning_views.topic_article, name="topic-article"),
    path("api/v1/topics/<str:topic_id>/terms/", learning_views.topic_terms, name="topic-terms"),
    path("api/v1/topics/<str:topic_id>/attempts/", assessments_views.start_attempt, name="attempt-start"),
    path("api/v1/attempts/", assessments_views.attempt_history, name="attempt-history"),
    path("api/v1/attempts/<str:attempt_id>/", assessments_views.attempt_detail, name="attempt-detail"),
    path("api/v1/attempts/<str:attempt_id>/submit/", assessments_views.submit_attempt, name="attempt-submit"),
]
