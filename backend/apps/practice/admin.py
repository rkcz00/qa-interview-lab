from django import forms
from django.contrib import admin
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.db.models import Model
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse

from apps.learning.changes import ContentWriteError, EditConflict, InvalidRevision, edit_topics
from apps.learning.content_admin import RevisionForm, RevisionedContentAdmin, read_revision
from apps.learning.models import TopicStatus

from .models import PracticeTask, PracticeTaskTranslation, SourceType, TopicPractice
from .checking import InvalidAnswer, NormalizationMode, normalize_answer


class PracticeContentAdmin(RevisionedContentAdmin):
    def save_model(self, request, obj, form, change):
        _, expected = form.topic_and_revision()
        obj.save(expected_revision=expected)

    def delete_model(self, request, obj):
        obj.delete(expected_revision=read_revision(request.POST.get("expected_revision")))


@admin.register(TopicPractice)
class TopicPracticeAdmin(PracticeContentAdmin):
    topic_path = "topic"
    readonly_fields = ("created_at", "updated_at")


class TaskForm(RevisionForm):
    confirm_expected_answer = forms.BooleanField(
        required=False, label="Подтверждаю намеренный пустой эталон",
        help_text="При редактировании Published с пустым эталоном требуется подтверждение.",
    )
    confirm_sql_scalar = forms.BooleanField(
        required=False, label="SQL детерминирован и возвращает ровно одну строку и один столбец",
        help_text="Редактор проверяет schema/data/диалект и формат. SQL не выполняется приложением.",
    )

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("normalization_mode")
        if "expected_answer" in cleaned and mode in NormalizationMode.values:
            try:
                # HTML textareas submit CRLF. Prepare the editor's canonical reference
                # with the declared policy, preserving significant whitespace in exact mode.
                cleaned["expected_answer"] = normalize_answer(cleaned["expected_answer"], mode)
            except InvalidAnswer:
                self.add_error("expected_answer", "Недопустимый эталон или превышен лимит.")
        if self.instance.status == TopicStatus.PUBLISHED:
            if cleaned.get("expected_answer") == "" and not cleaned.get("confirm_expected_answer"):
                self.add_error("confirm_expected_answer", "Подтвердите намеренный пустой эталон.")
            if cleaned.get("source_type") == SourceType.SQL and not cleaned.get("confirm_sql_scalar"):
                self.add_error("confirm_sql_scalar", "Подтвердите scalar-result и детерминизм SQL.")
        return cleaned


@admin.register(PracticeTask)
class PracticeTaskAdmin(PracticeContentAdmin):
    form = TaskForm
    topic_path = "topic_practice__topic"
    readonly_fields = ("status", "created_at", "updated_at")
    list_display = ("id", "topic_practice", "status", "source_type", "updated_at")
    actions = ("publish_selected", "unpublish_selected")

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name in {"expected_answer", "source_text", "input_data", "environment", "output_spec"}:
            kwargs["strip"] = False
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    @admin.action(permissions=("change",), description="Опубликовать выбранные задания")
    def publish_selected(self, request, queryset):
        return self.change_status(request, queryset, TopicStatus.PUBLISHED, "publish_selected")

    @admin.action(permissions=("change",), description="Перевести задания в Draft")
    def unpublish_selected(self, request, queryset):
        return self.change_status(request, queryset, TopicStatus.DRAFT, "unpublish_selected")

    def change_status(self, request, queryset, status, action):
        tasks = list(queryset.select_related("topic_practice__topic").order_by("pk"))
        if request.POST.get("confirm") != "yes":
            return TemplateResponse(request, "admin/practice/confirm_status.html", {
                **self.admin_site.each_context(request), "title": "Подтвердите статус практики",
                "tasks": tasks, "publish": status == TopicStatus.PUBLISHED,
                "action": action, "checkbox_name": ACTION_CHECKBOX_NAME,
            })
        try:
            selected = {read_revision(value) for value in request.POST.getlist(ACTION_CHECKBOX_NAME)}
            if selected != {task.pk for task in tasks} or not selected:
                raise EditConflict()
            revisions = {}
            for value in request.POST.getlist("expected_revision"):
                key, separator, revision = value.partition(":")
                topic_id = read_revision(key)
                if not separator or topic_id in revisions:
                    raise InvalidRevision()
                revisions[topic_id] = read_revision(revision)
            if set(revisions) != {task.topic_practice.topic_id for task in tasks}:
                raise InvalidRevision()
            if status == TopicStatus.PUBLISHED and request.POST.get("confirm_expected") != "yes":
                raise InvalidRevision()
            # The same root lock as start/child writes. Validate all before commit.
            with edit_topics(revisions, using=queryset.db):
                for task in tasks:
                    task.status = status
                    # Avoid a nested Topic transaction/revision bump from save().
                    Model.save(task, using=queryset.db, update_fields=("status", "updated_at"))
                    self.log_change(request, task, "Изменён статус практики.")
        except ContentWriteError as error:
            return self.write_error(request, error)
        self.message_user(request, "Статус практики обновлён.")
        return HttpResponseRedirect(request.get_full_path())


@admin.register(PracticeTaskTranslation)
class PracticeTranslationAdmin(PracticeContentAdmin):
    topic_path = "task__topic_practice__topic"
