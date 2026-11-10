from django.contrib import admin

from .models import Choice, ChoiceTranslation, Question, QuestionTranslation


admin.site.register([Question, QuestionTranslation, Choice, ChoiceTranslation])
