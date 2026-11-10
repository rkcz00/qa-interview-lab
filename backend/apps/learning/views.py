import logging
from functools import wraps

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from rest_framework.exceptions import ValidationError

from config.api import authentication_required, error_response, method_not_allowed

from .models import TermTranslation, Topic, TopicStatus, TopicTranslation
from .serializers import ArticleSerializer, ContentLanguageSerializer, TermSerializer, TopicSummarySerializer


logger = logging.getLogger(__name__)


def _learner_read(view):
    @wraps(view)
    @never_cache
    def read(request, *args, **kwargs):
        if request.method != "GET":
            return method_not_allowed("GET")
        try:
            if not request.user.is_authenticated:
                return authentication_required()
            return JsonResponse({"data": view(request, *args, **kwargs)})
        except Http404:
            return error_response("not_found", "Topic not found.", 404)
        except ValidationError:
            return error_response("validation_error", "Invalid query parameters.", 400)
        except Exception as exc:
            logger.error("Learner content read failed (%s)", type(exc).__name__)
            return error_response("internal_error", "Content could not be loaded.", 500)

    return read


def _language(query):
    if set(query) - {"language"} or len(query.getlist("language")) > 1:
        raise ValidationError("Expected only one language parameter.")
    serializer = ContentLanguageSerializer(data=query.dict())
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data["language"]


def _published_topic_id(topic_id):
    if len(topic_id) > 19 or not topic_id.isascii() or not topic_id.isdecimal():
        raise Http404
    pk = int(topic_id)
    if str(pk) != topic_id or not 1 <= pk <= 2**63 - 1:
        raise Http404
    if not Topic.objects.filter(pk=pk, status=TopicStatus.PUBLISHED).exists():
        raise Http404
    return pk


def _topic_translations(language):
    return TopicTranslation.objects.filter(topic__status=TopicStatus.PUBLISHED, language=language)


@_learner_read
def topic_catalog(request):
    translations = _topic_translations(_language(request.GET)).only("topic_id", "title").order_by("topic_id")
    return TopicSummarySerializer(translations, many=True).data


@_learner_read
def topic_article(request, topic_id):
    pk = _published_topic_id(topic_id)
    translation = get_object_or_404(_topic_translations(_language(request.GET)), topic_id=pk)
    return ArticleSerializer(translation).data


@_learner_read
def topic_terms(request, topic_id):
    pk = _published_topic_id(topic_id)
    translations = list(
        TermTranslation.objects.select_related("term")
        .filter(term__topic_id=pk, term__topic__status=TopicStatus.PUBLISHED, language=_language(request.GET))
        .order_by("term__position", "term_id")
    )
    if not translations:  # Every Published topic has a bilingual glossary.
        raise Http404
    return TermSerializer(translations, many=True).data
