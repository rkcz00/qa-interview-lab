from django.contrib import admin
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse

from .changes import ContentWriteError, EditConflict, InvalidRevision, edit_topics
from .content_admin import RevisionedContentAdmin, read_revision
from .models import Term, TermTranslation, Topic, TopicStatus, TopicTranslation


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


@admin.register(TopicTranslation, Term)
class TopicChildAdmin(RevisionedContentAdmin):
    topic_path = "topic"


@admin.register(TermTranslation)
class TermTranslationAdmin(RevisionedContentAdmin):
    topic_path = "term__topic"
