from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.db.models.functions import Length
from django.db.models.lookups import LessThanOrEqual

from apps.learning.changes import InvalidRevision, edit_topics
from apps.learning.models import Language, Topic, TopicStatus, require_translations

from .checking import ANSWER_MAX_LENGTH, InvalidAnswer, NormalizationMode, Verdict, normalize_answer


class PracticeKind(models.TextChoices):
    SINGLE_CORRECT_ANSWER = "single_correct_answer", "Один точный результат"


class SourceType(models.TextChoices):
    PYTHON = "python", "Python"
    SQL = "sql", "SQL (одна строка, один столбец)"
    OTHER = "other", "Другой технический контекст"


class SubmissionStatus(models.TextChoices):
    IN_PROGRESS = "in_progress", "В работе"
    SUBMITTED = "submitted", "Отправлено"


class ProtectedWritesQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Используйте доменную операцию записи.", code="protected_write")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Используйте доменную операцию записи.", code="protected_write")

    def bulk_update(self, objs, fields, **kwargs):
        raise ValidationError("Используйте доменную операцию записи.", code="protected_write")


class ContentQuerySet(ProtectedWritesQuerySet):
    def create(self, *, expected_revision=None, **kwargs):
        obj = self.model(**kwargs)
        obj.save(force_insert=True, using=self.db, expected_revision=expected_revision)
        return obj

    def delete(self):
        raise ValidationError("Удаляйте контент с ожидаемой ревизией.", code="protected_write")


class PracticeContent(models.Model):
    """Every public ORM write uses the same Topic lock and optimistic revision."""

    objects = ContentQuerySet.as_manager()
    parent_field = ""
    topic_path = ""

    class Meta:
        abstract = True

    @property
    def topic_id_for_write(self):
        obj = self
        for field in self.topic_path.split("__"):
            obj = getattr(obj, field)
        return obj.pk

    def _check_parent(self, using):
        if not self._state.adding:
            field = self._meta.get_field(self.parent_field).attname
            original = type(self).objects.using(using).values_list(field, flat=True).get(pk=self.pk)
            if original != getattr(self, field):
                raise ValidationError("Родительская связь неизменяема.", code="immutable_parent")

    def save(self, *args, expected_revision=None, **kwargs):
        if type(expected_revision) is not int or not 1 <= expected_revision <= 2**63 - 1:
            raise InvalidRevision()
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        kwargs["using"] = using
        with edit_topics({self.topic_id_for_write: expected_revision}, using=using):
            self._check_parent(using)
            self.full_clean(validate_unique=False, validate_constraints=False)
            if self._state.adding:
                kwargs["force_insert"] = True
            return super().save(*args, **kwargs)

    def delete(self, *args, expected_revision=None, **kwargs):
        if type(expected_revision) is not int or not 1 <= expected_revision <= 2**63 - 1:
            raise InvalidRevision()
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        kwargs["using"] = using
        with edit_topics({self.topic_id_for_write: expected_revision}, using=using):
            self._check_parent(using)
            return super().delete(*args, **kwargs)


class TopicPractice(PracticeContent):
    parent_field = "topic"
    topic_path = "topic"
    topic = models.OneToOneField(Topic, on_delete=models.PROTECT, related_name="practice")
    practice_kind = models.CharField(
        max_length=21, choices=PracticeKind.choices, default=PracticeKind.SINGLE_CORRECT_ANSWER,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=models.Q(practice_kind__in=PracticeKind.values), name="practice_kind_valid",
        )]


class PracticeTask(PracticeContent):
    parent_field = "topic_practice"
    topic_path = "topic_practice__topic"
    topic_practice = models.OneToOneField(TopicPractice, on_delete=models.PROTECT, related_name="task")
    status = models.CharField(max_length=9, choices=TopicStatus.choices, default=TopicStatus.DRAFT)
    source_type = models.CharField(max_length=6, choices=SourceType.choices, default=SourceType.OTHER)
    source_text = models.TextField(blank=True)
    input_data = models.TextField(blank=True)
    environment = models.TextField(blank=True)
    output_spec = models.TextField(blank=True, help_text="Для SQL: только одна строка и один столбец.")
    expected_answer = models.TextField(blank=True, help_text="Серверный эталон; пустота должна быть намеренной.")
    normalization_mode = models.CharField(
        max_length=16, choices=NormalizationMode.choices, default=NormalizationMode.LF_TRIM_OUTER_V1,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(status__in=TopicStatus.values), name="practice_task_status_valid"),
            models.CheckConstraint(condition=models.Q(source_type__in=SourceType.values), name="practice_source_valid"),
            models.CheckConstraint(
                condition=models.Q(normalization_mode__in=NormalizationMode.values), name="practice_mode_valid",
            ),
            models.CheckConstraint(
                condition=LessThanOrEqual(Length("expected_answer"), ANSWER_MAX_LENGTH),
                name="practice_expected_length",
            ),
        ]

    def clean(self):
        super().clean()
        try:
            normalize_answer(self.expected_answer, self.normalization_mode)
        except (InvalidAnswer, ValueError):
            raise ValidationError("Недопустимый эталон или режим нормализации.", code="invalid_expected") from None

    def validate_for_publication(self):
        self.clean()
        if any(not getattr(self, name).strip() for name in ("source_text", "environment", "output_spec")):
            raise ValidationError("Заполните техническое условие, окружение и формат результата.")
        if self.source_type == SourceType.SQL and not self.input_data.strip():
            raise ValidationError("Для SQL задайте схему и полный набор входных данных.")
        if normalize_answer(self.expected_answer, self.normalization_mode) != self.expected_answer:
            raise ValidationError("Эталон должен быть каноническим для выбранного режима.")
        require_translations(self.translations.all(), fields=("title", "prompt"), label="Практическое задание")


class PracticeTaskTranslation(PracticeContent):
    parent_field = "task"
    topic_path = "task__topic_practice__topic"
    task = models.ForeignKey(PracticeTask, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=2, choices=Language.choices)
    title = models.TextField(blank=True)
    prompt = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("task", "language"), name="practice_translation_unique"),
            models.CheckConstraint(condition=models.Q(language__in=Language.values), name="practice_language_valid"),
        ]


class PracticeSubmission(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="practice_submissions", editable=False)
    task = models.ForeignKey(PracticeTask, on_delete=models.PROTECT, related_name="submissions", editable=False)
    status = models.CharField(max_length=11, choices=SubmissionStatus.choices, default=SubmissionStatus.IN_PROGRESS)
    task_snapshot = models.JSONField(editable=False)
    submitted_answer = models.TextField(null=True, editable=False)
    submitted_language = models.CharField(max_length=2, choices=Language.choices, null=True, editable=False)
    verdict = models.CharField(max_length=9, choices=Verdict.choices, null=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, editable=False)

    objects = ProtectedWritesQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(
                    status=SubmissionStatus.IN_PROGRESS, submitted_answer__isnull=True,
                    submitted_language__isnull=True, verdict__isnull=True, submitted_at__isnull=True,
                ) | models.Q(
                    status=SubmissionStatus.SUBMITTED, submitted_answer__isnull=False,
                    submitted_language__isnull=False, submitted_language__in=Language.values,
                    verdict__isnull=False, verdict__in=Verdict.values, submitted_at__isnull=False,
                )), name="practice_submission_state",
            ),
            models.CheckConstraint(
                condition=LessThanOrEqual(Length("submitted_answer"), ANSWER_MAX_LENGTH),
                name="practice_answer_length",
            ),
        ]
        indexes = [models.Index(fields=("user", "status", "id"), name="practice_owner_status_idx")]

    def save(self, *args, **kwargs):
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        kwargs["using"] = using
        if self._state.adding:
            if self.status != SubmissionStatus.IN_PROGRESS or any(value is not None for value in (
                self.submitted_answer, self.submitted_language, self.verdict, self.submitted_at,
            )):
                raise ValidationError("Новая работа должна быть незавершённой.", code="invalid_initial_state")
            kwargs["force_insert"] = True
            return super().save(*args, **kwargs)
        with transaction.atomic(using=using):
            stored = type(self).objects.using(using).select_for_update().get(pk=self.pk)
            frozen = ("user_id", "task_id", "task_snapshot", "created_at")
            if stored.status == SubmissionStatus.SUBMITTED:
                frozen += ("status", "submitted_answer", "submitted_language", "verdict", "submitted_at")
            if any(getattr(stored, field) != getattr(self, field) for field in frozen):
                raise ValidationError("Сохранённая работа неизменяема.", code="immutable_submission")
            return super().save(*args, **kwargs)
