from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import models, router
from django.template.response import TemplateResponse

from .changes import ContentWriteError, EditConflict, InvalidRevision, edit_topics
from .models import Topic


def get_topic(obj, path):
    if path:
        for field in path.split("__"):
            obj = getattr(obj, field)
    return obj


def read_revision(value):
    try:
        return forms.IntegerField(min_value=1, max_value=2**63 - 1).clean(value)
    except ValidationError as error:
        raise InvalidRevision() from error


class RevisionForm(forms.ModelForm):
    topic_path = ""
    expected_revision = forms.IntegerField(min_value=1, max_value=2**63 - 1, required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk is not None:
            self.initial["expected_revision"] = get_topic(self.instance, self.topic_path).revision
            self.fields["expected_revision"].required = True

    def topic_and_revision(self):
        expected = self.cleaned_data.get("expected_revision")
        if self.instance.pk is not None:
            return get_topic(self.instance, self.topic_path), expected

        parent_field, _, related_path = self.topic_path.partition("__")
        parent = self.cleaned_data.get(parent_field)
        if parent is None:
            return None, expected
        if expected is None:
            expected = self.fields[parent_field].expected_revision
        return get_topic(parent, related_path), expected

    def full_clean(self):
        super().full_clean()
        if self._errors:
            # A stale form can become invalid too, for example when the first edit added the same translation.
            topic, expected = self.topic_and_revision()
            if topic is not None and expected is not None:
                current = Topic.objects.using(topic._state.db).filter(pk=topic.pk).values_list("revision", flat=True).first()
                if current != expected:
                    raise EditConflict()


class ParentRevisionField(forms.ModelChoiceField):
    """The add form's parent option carries the revision seen when it was rendered."""

    def __init__(self, *args, topic_path, **kwargs):
        super().__init__(*args, **kwargs)
        self.topic_path = topic_path
        self.expected_revision = None

    def prepare_value(self, value):
        prepared = super().prepare_value(value)
        if isinstance(value, models.Model):
            return f"{prepared}:{get_topic(value, self.topic_path).revision}"
        return prepared

    def clean(self, value):
        if value:
            parent_id, separator, revision = str(value).partition(":")
            if separator:
                self.expected_revision = read_revision(revision)
                value = parent_id
        return super().clean(value)


class RevisionedContentAdmin(admin.ModelAdmin):
    form = RevisionForm
    topic_path = ""
    actions = None
    delete_confirmation_template = "admin/content/delete_confirmation.html"

    @property
    def parent_field(self):
        return self.topic_path.partition("__")[0]

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if self.topic_path:
            return queryset.select_related(self.topic_path)
        return queryset

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if obj is not None and self.parent_field:
            return (*fields, self.parent_field)
        return fields

    def get_form(self, request, obj=None, **kwargs):
        form_class = super().get_form(request, obj, **kwargs)
        return type(form_class.__name__, (form_class,), {"topic_path": self.topic_path})

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name != self.parent_field:
            return super().formfield_for_dbfield(db_field, request, **kwargs)

        # Plain select: each rendered option includes its parent topic's revision.
        related_path = self.topic_path.partition("__")[2]
        queryset = db_field.remote_field.model._default_manager.all()
        if related_path:
            queryset = queryset.select_related(related_path)
        return db_field.formfield(form_class=ParentRevisionField, topic_path=related_path, queryset=queryset, **kwargs)

    def save_model(self, request, obj, form, change):
        if self.model is Topic and not change:
            return super().save_model(request, obj, form, change)

        topic, expected = form.topic_and_revision()
        if topic is None or expected is None:
            raise InvalidRevision()

        using = router.db_for_write(self.model, instance=obj)
        with edit_topics({topic.pk: expected}, using=using) as topics:
            if self.model is not Topic:
                super().save_model(request, obj, form, change)
        if self.model is Topic:
            obj.revision = topics[topic.pk].revision

    def render_delete_form(self, request, context):
        context["expected_revision"] = get_topic(context["object"], self.topic_path).revision
        return super().render_delete_form(request, context)

    def delete_model(self, request, obj):
        expected = read_revision(request.POST.get("expected_revision"))
        topic_id = get_topic(obj, self.topic_path).pk
        using = router.db_for_write(self.model, instance=obj)
        with edit_topics({topic_id: expected}, using=using) as topics:
            target = topics[topic_id] if self.model is Topic else obj
            super().delete_model(request, target)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except ContentWriteError as error:
            return self.write_error(request, error)

    def delete_view(self, request, object_id, extra_context=None):
        try:
            return super().delete_view(request, object_id, extra_context)
        except ContentWriteError as error:
            return self.write_error(request, error)

    def write_error(self, request, error):
        context = {
            **self.admin_site.each_context(request),
            "title": "Изменение не сохранено",
            "error_code": error.error_code,
            "details": error.messages,
            "retry_url": request.path,
        }
        return TemplateResponse(request, "admin/content/write_error.html", context, status=error.status)
