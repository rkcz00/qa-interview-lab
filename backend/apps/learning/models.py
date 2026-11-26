from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import MinValueValidator
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
        require_translations(self.translations.all(), fields=("title",), label="Тема")
        sections = list(self.sections.filter(status=TopicStatus.PUBLISHED).prefetch_related("translations"))
        if not sections:
            raise ValidationError("В теме нужен хотя бы один Published-раздел.", code="missing_sections")
        for section in sections:
            section.validate_for_publication()

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
        for section in self.sections.filter(status=TopicStatus.PUBLISHED).prefetch_related("translations"):
            section.validate_for_publication()
        if self.status == TopicStatus.PUBLISHED:
            self.validate_for_publication()
        # Practice may remain Draft independently. Published practice must stay complete
        # even while its parent Topic is Draft; all writers hold this Topic's lock.
        try:
            task = self.practice.task
        except ObjectDoesNotExist:
            task = None
        if task is not None and task.status == TopicStatus.PUBLISHED:
            task.validate_for_publication()
        self.revision += 1
        super().save(using=using, update_fields=("status", "revision", "updated_at"))


class TopicTranslationQuerySet(models.QuerySet):
    def bulk_create(self, objs, **kwargs):
        if "article_body" in (kwargs.get("update_fields") or ()):
            raise ValidationError("Legacy-тело статьи доступно только для чтения.", code="legacy_read_only")
        return super().bulk_create(objs, **kwargs)

    def update(self, **kwargs):
        if "article_body" in kwargs:
            raise ValidationError("Legacy-тело статьи доступно только для чтения.", code="legacy_read_only")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        if "article_body" in fields:
            raise ValidationError("Legacy-тело статьи доступно только для чтения.", code="legacy_read_only")
        return super().bulk_update(objs, fields, **kwargs)


class TopicTranslation(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=2, choices=Language.choices)
    title = models.TextField(blank=True)
    article_body = models.TextField(blank=True, editable=False)

    objects = TopicTranslationQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if not self._state.adding and self.pk is not None:
            using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
            original = type(self).objects.using(using).get(pk=self.pk)
            if self.article_body != original.article_body:
                raise ValidationError("Legacy-тело статьи доступно только для чтения.", code="legacy_read_only")
        return super().save(*args, **kwargs)

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


class SectionQuerySet(models.QuerySet):
    def create(self, *, expected_revision=None, **kwargs):
        obj = self.model(**kwargs)
        obj.save(using=self.db, expected_revision=expected_revision)
        return obj

    def update(self, **kwargs):
        raise ValidationError("Разделы меняются через запись дерева Topic.", code="revision_required")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Разделы меняются через запись дерева Topic.", code="revision_required")

    def bulk_update(self, objs, fields, **kwargs):
        raise ValidationError("Разделы меняются через запись дерева Topic.", code="revision_required")

    def delete(self):
        raise ValidationError("Разделы удаляются через запись дерева Topic.", code="revision_required")


class SectionContent(models.Model):
    """Each public write participates in the existing root optimistic transaction."""

    objects = SectionQuerySet.as_manager()
    parent_field = ""

    class Meta:
        abstract = True

    def _topic_id(self, using):
        return self.topic_id if self.parent_field == "topic" else TopicSection.objects.using(using).get(pk=self.section_id).topic_id

    def _check_parent(self, using):
        if not self._state.adding:
            field = self.parent_field + "_id"
            original = type(self).objects.using(using).get(pk=self.pk)
            if getattr(original, field) != getattr(self, field):
                raise ValidationError("Родителя раздела/перевода менять нельзя.", code="immutable_parent")

    def save(self, *, expected_revision=None, using=None, **kwargs):
        from .changes import InvalidRevision, edit_topics

        if type(expected_revision) is not int or not 1 <= expected_revision <= 2**63 - 1:
            raise InvalidRevision()
        using = using or router.db_for_write(type(self), instance=self)
        with edit_topics({self._topic_id(using): expected_revision}, using=using):
            self._check_parent(using)
            # The deferred position constraint permits swaps inside one root transaction.
            self.full_clean(validate_unique=False, validate_constraints=False)
            return super().save(using=using, **kwargs)

    def delete(self, *, expected_revision=None, using=None, keep_parents=False):
        from .changes import InvalidRevision, edit_topics

        if type(expected_revision) is not int or not 1 <= expected_revision <= 2**63 - 1:
            raise InvalidRevision()
        using = using or router.db_for_write(type(self), instance=self)
        with edit_topics({self._topic_id(using): expected_revision}, using=using):
            self._check_parent(using)
            return super().delete(using=using, keep_parents=keep_parents)


class TopicSection(SectionContent):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="sections")
    position = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    status = models.CharField(max_length=9, choices=TopicStatus.choices, default=TopicStatus.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    parent_field = "topic"

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(fields=("topic", "position"), name="learning_section_position_unique", deferrable=models.Deferrable.DEFERRED),
            models.CheckConstraint(condition=models.Q(position__gte=1), name="learning_section_position_positive"),
            models.CheckConstraint(condition=models.Q(status__in=TopicStatus.values), name="learning_section_status_valid"),
        ]

    def validate_for_publication(self):
        require_translations(self.translations.all(), fields=("title", "article_body"), label=f"Раздел {self.pk}")


class TopicSectionTranslation(SectionContent):
    section = models.ForeignKey(TopicSection, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=2, choices=Language.choices)
    title = models.TextField(blank=True)
    article_body = models.TextField(blank=True)
    parent_field = "section"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("section", "language"), name="learning_section_translation_unique"),
            models.CheckConstraint(condition=models.Q(language__in=Language.values), name="learning_section_translation_language_valid"),
        ]
