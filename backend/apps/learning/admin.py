from django.contrib import admin
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.db.models import Model
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse

from .changes import ContentWriteError, EditConflict, InvalidRevision, edit_topics
from .content_admin import RevisionForm, RevisionedContentAdmin, read_revision
from .models import Term, TermTranslation, Topic, TopicSection, TopicSectionTranslation, TopicStatus, TopicTranslation


@admin.register(Topic)
class TopicAdmin(RevisionedContentAdmin):
    readonly_fields = ("status", "revision")
    list_display = ("id", "status", "revision", "updated_at")
    actions = ("publish_selected", "unpublish_selected")

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.action(permissions=("change",), description="Опубликовать выбранные темы")
    def publish_selected(self, request, queryset):
        return self.change_status(request, queryset, TopicStatus.PUBLISHED, "publish_selected")

    @admin.action(permissions=("change",), description="Перевести выбранные темы в Draft")
    def unpublish_selected(self, request, queryset):
        return self.change_status(request, queryset, TopicStatus.DRAFT, "unpublish_selected")

    def change_status(self, request, queryset, status, action):
        if request.POST.get("confirm") != "yes":
            context = {
                **self.admin_site.each_context(request),
                "title": "Подтвердите смену статуса тем",
                "topics": queryset.order_by("pk"),
                "target_status": status.label,
                "action": action,
                "checkbox_name": ACTION_CHECKBOX_NAME,
            }
            return TemplateResponse(request, "admin/content/confirm_status.html", context)

        try:
            selected = {read_revision(value) for value in request.POST.getlist(ACTION_CHECKBOX_NAME)}
            revisions = {}
            for value in request.POST.getlist("expected_revision"):
                key, _, revision = value.partition(":")
                pk = read_revision(key)
                if pk in revisions:
                    raise InvalidRevision()
                revisions[pk] = read_revision(revision)
            if not revisions or revisions.keys() != selected:
                raise InvalidRevision()
            if set(queryset.values_list("pk", flat=True)) != selected:
                raise EditConflict()

            with edit_topics(revisions, using=queryset.db) as topics:
                for topic in topics.values():
                    topic.status = status
                    self.log_change(request, topic, f"Статус темы: {status.label}.")
        except ContentWriteError as error:
            return self.write_error(request, error)

        self.message_user(request, f"Статус тем обновлён: {status.label}.")
        return HttpResponseRedirect(request.get_full_path())


@admin.register(Term)
class TopicChildAdmin(RevisionedContentAdmin):
    topic_path = "topic"


@admin.register(TopicTranslation)
class TopicTranslationAdmin(TopicChildAdmin):
    readonly_fields = ("article_body",)


@admin.register(TermTranslation)
class TermTranslationAdmin(RevisionedContentAdmin):
    topic_path = "term__topic"


class SectionForm(RevisionForm):
    def clean(self):
        cleaned = super().clean()
        # On change Django excludes the read-only parent from constraint checks.
        # Validate these two known conflicts in the form, before the root write.
        field = "position" if isinstance(self.instance, TopicSection) else "language"
        parent = self.instance.parent_field
        parent_id = getattr(self.instance, parent + "_id", None)
        if not self.instance.pk:
            parent_id = getattr(cleaned.get(parent), "pk", None)
        value = cleaned.get(field)
        if parent_id is not None and value is not None and type(self.instance).objects.filter(
            **{parent + "_id": parent_id, field: value},
        ).exclude(pk=self.instance.pk).exists():
            self.add_error(field, "Такая позиция или перевод уже существует у выбранного родителя.")
        return cleaned


class SectionContentAdmin(RevisionedContentAdmin):
    form = SectionForm
    def save_model(self, request, obj, form, change):
        _, expected = form.topic_and_revision()
        obj.save(expected_revision=expected)

    def delete_model(self, request, obj):
        obj.delete(expected_revision=read_revision(request.POST.get("expected_revision")))


@admin.register(TopicSection)
class TopicSectionAdmin(SectionContentAdmin):
    topic_path = "topic"
    readonly_fields = ("status", "created_at", "updated_at")
    list_display = ("id", "topic", "position", "status", "updated_at")
    actions = ("publish_selected", "unpublish_selected")

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.action(permissions=("change",), description="Опубликовать выбранные разделы")
    def publish_selected(self, request, queryset):
        return self.change_status(request, queryset, TopicStatus.PUBLISHED, "publish_selected")

    @admin.action(permissions=("change",), description="Перевести разделы в Draft")
    def unpublish_selected(self, request, queryset):
        return self.change_status(request, queryset, TopicStatus.DRAFT, "unpublish_selected")

    def change_status(self, request, queryset, status, action):
        sections = list(queryset.select_related("topic").order_by("pk"))
        if request.POST.get("confirm") != "yes":
            return TemplateResponse(request, "admin/content/confirm_sections.html", {
                **self.admin_site.each_context(request), "title": "Подтвердите статус разделов",
                "sections": sections, "target_status": status.label,
                "revisions": sorted({section.topic_id: section.topic.revision for section in sections}.items()),
                "action": action, "checkbox_name": ACTION_CHECKBOX_NAME,
            })
        try:
            selected = {read_revision(value) for value in request.POST.getlist(ACTION_CHECKBOX_NAME)}
            if not selected or selected != {section.pk for section in sections}:
                raise EditConflict()
            revisions = {}
            for value in request.POST.getlist("expected_revision"):
                key, separator, revision = value.partition(":")
                topic_id = read_revision(key)
                if not separator or topic_id in revisions:
                    raise InvalidRevision()
                revisions[topic_id] = read_revision(revision)
            if set(revisions) != {section.topic_id for section in sections}:
                raise InvalidRevision()
            with edit_topics(revisions, using=queryset.db):
                for section in sections:
                    section.status = status
                    Model.save(section, using=queryset.db, update_fields=("status", "updated_at"))
                    self.log_change(request, section, "Изменён статус раздела.")
        except ContentWriteError as error:
            return self.write_error(request, error)
        self.message_user(request, "Статус разделов обновлён.")
        return HttpResponseRedirect(request.get_full_path())


@admin.register(TopicSectionTranslation)
class TopicSectionTranslationAdmin(SectionContentAdmin):
    topic_path = "section__topic"

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name in {"title", "article_body"}:
            kwargs["strip"] = False
        return super().formfield_for_dbfield(db_field, request, **kwargs)
