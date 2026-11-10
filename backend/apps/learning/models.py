from django.core.exceptions import ValidationError
from django.db import models, router


class Language(models.TextChoices):
    RU = "ru", "Русский"
    EN = "en", "English"


class TopicStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"


def require_translations(translations, *, fields, label):
    by_language = {translation.language: translation for translation in translations}
    for language in Language.values:
        translation = by_language.get(language)
        if translation is None:
            raise ValidationError(f"{label}: отсутствует перевод {language}.", code="missing_translation")
        for field in fields:
            if not (getattr(translation, field) or "").strip():
                raise ValidationError(
                    f"{label}: поле {field} в переводе {language} пустое.",
                    code="blank_translation",
                )


class TopicQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if {"status", "revision"}.intersection(kwargs):
            raise ValidationError("Статус и ревизия меняются через операцию записи темы.", code="bulk_status")
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        topics = list(objs)
        if any(topic.status != TopicStatus.DRAFT or topic.revision != 1 for topic in topics):
            raise ValidationError("Новые темы создаются в Draft с ревизией 1.", code="draft_required")
        if {"status", "revision"}.intersection(kwargs.get("update_fields") or ()):
            raise ValidationError("Статус и ревизия меняются через операцию записи темы.", code="bulk_status")
        return super().bulk_create(topics, **kwargs)


class Topic(models.Model):
    status = models.CharField(max_length=9, choices=TopicStatus.choices, default=TopicStatus.DRAFT)
    revision = models.PositiveBigIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TopicQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=TopicStatus.values), name="learning_topic_status_valid"
            ),
            models.CheckConstraint(condition=models.Q(revision__gte=1), name="learning_topic_revision_positive"),
        ]

    def _require_saved_topic(self):
        if self._state.adding or self.pk is None:
            raise ValidationError("Сначала сохраните тему в Draft.", code="draft_required")

    def validate_for_publication(self):
        self._require_saved_topic()
        require_translations(self.translations.all(), fields=("title", "article_body"), label="Статья")

        terms = list(self.terms.prefetch_related("translations"))
        if not terms:
            raise ValidationError("В теме нужен хотя бы один термин.", code="missing_terms")
        for term in terms:
            require_translations(term.translations.all(), fields=("name", "definition"), label=f"Термин {term.pk}")

        questions = list(self.questions.prefetch_related("translations", "choices__translations"))
        if not questions:
            raise ValidationError("В теме нужен хотя бы один вопрос.", code="missing_questions")
        for question in questions:
            question.validate_for_publication()

    def clean(self):
        super().clean()
        if self.status == TopicStatus.PUBLISHED:
            self.validate_for_publication()

    def save(self, *, force_insert=False, force_update=False, using=None, update_fields=None):
        if self.status not in TopicStatus.values:
            raise ValidationError("Допустимые статусы темы: Draft и Published.", code="invalid_status")

        if self._state.adding or self.pk is None or force_insert:
            if self.status != TopicStatus.DRAFT or self.revision != 1:
                raise ValidationError("Новые темы создаются в Draft с ревизией 1.", code="draft_required")
            return super().save(
                force_insert=force_insert or not force_update, force_update=force_update,
                using=using, update_fields=update_fields,
            )

        if update_fields is not None:
            update_fields = tuple(update_fields)
            if "revision" in update_fields:
                raise ValidationError("Ревизия меняется через операцию записи темы.", code="invalid_revision")
            if "status" not in update_fields:
                return super().save(force_update=force_update, using=using, update_fields=update_fields)

        from .changes import edit_topics

        using = using or router.db_for_write(type(self), instance=self)
        with edit_topics({self.pk: self.revision}, using=using) as topics:
            stored = topics[self.pk]
            stored.status = self.status
        self.revision = stored.revision
        self.updated_at = stored.updated_at

    def _save_content_revision(self, using):
        if self.status == TopicStatus.PUBLISHED:
            self.validate_for_publication()
        self.revision += 1
        super().save(using=using, update_fields=("status", "revision", "updated_at"))


class TopicTranslation(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=2, choices=Language.choices)
    title = models.TextField(blank=True)
    article_body = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("topic", "language"), name="learning_topic_translation_unique"),
            models.CheckConstraint(
                condition=models.Q(language__in=Language.values), name="learning_topic_translation_language_valid"
            ),
        ]


class Term(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="terms")
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ("position", "id")


class TermTranslation(models.Model):
    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=2, choices=Language.choices)
    name = models.TextField(blank=True)
    definition = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("term", "language"), name="learning_term_translation_unique"),
            models.CheckConstraint(
                condition=models.Q(language__in=Language.values), name="learning_term_translation_language_valid"
            ),
        ]
