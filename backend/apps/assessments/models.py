from django.core.exceptions import ValidationError
from django.db import models

from apps.learning.models import Language, Topic, require_translations


class QuestionType(models.TextChoices):
    SINGLE_CHOICE = "single_choice", "Single-choice"
    MULTIPLE_CHOICE = "multiple_choice", "Multiple-choice"


class Question(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="questions")
    question_type = models.CharField(max_length=15, choices=QuestionType.choices)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(question_type__in=QuestionType.values),
                name="assessments_question_type_valid",
            ),
        ]

    def validate_for_publication(self):
        label = f"Вопрос {self.pk}"
        require_translations(self.translations.all(), fields=("text",), label=label)
        choices = list(self.choices.all())
        if len(choices) < 2:
            raise ValidationError(f"{label}: нужны минимум два варианта.", code="insufficient_choices")
        correct_count = sum(choice.is_correct for choice in choices)
        if self.question_type == QuestionType.SINGLE_CHOICE and correct_count != 1:
            raise ValidationError(f"{label}: нужен один правильный вариант.", code="invalid_correct_count")
        if self.question_type == QuestionType.MULTIPLE_CHOICE and correct_count < 2:
            raise ValidationError(f"{label}: нужны минимум два правильных варианта.", code="invalid_correct_count")
        for choice in choices:
            require_translations(choice.translations.all(), fields=("text",), label=f"Вариант {choice.pk}")


class QuestionTranslation(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=2, choices=Language.choices)
    text = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("question", "language"), name="assessments_question_translation_unique"),
            models.CheckConstraint(
                condition=models.Q(language__in=Language.values), name="assessments_question_translation_language_valid"
            ),
        ]


class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choices")
    position = models.PositiveIntegerField()
    is_correct = models.BooleanField(default=False)

    class Meta:
        ordering = ("position", "id")


class ChoiceTranslation(models.Model):
    choice = models.ForeignKey(Choice, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=2, choices=Language.choices)
    text = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("choice", "language"), name="assessments_choice_translation_unique"),
            models.CheckConstraint(
                condition=models.Q(language__in=Language.values), name="assessments_choice_translation_language_valid"
            ),
        ]
