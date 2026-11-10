from django.contrib import admin

from apps.learning.content_admin import RevisionedContentAdmin

from .models import Choice, ChoiceTranslation, Question, QuestionTranslation


@admin.register(Question)
class QuestionAdmin(RevisionedContentAdmin):
    topic_path = "topic"


@admin.register(QuestionTranslation, Choice)
class QuestionChildAdmin(RevisionedContentAdmin):
    topic_path = "question__topic"


@admin.register(ChoiceTranslation)
class ChoiceTranslationAdmin(RevisionedContentAdmin):
    topic_path = "choice__question__topic"
