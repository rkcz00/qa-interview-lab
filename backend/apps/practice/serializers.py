from rest_framework import serializers

from apps.assessments.serializers import _StrictRequestSerializer
from apps.learning.models import Language

from .checking import InvalidAnswer, validate_answer_text


class StartPracticeSerializer(_StrictRequestSerializer):
    language = serializers.ChoiceField(choices=Language.values)


class AnswerField(serializers.Field):
    def to_internal_value(self, data):
        try:
            return validate_answer_text(data)
        except InvalidAnswer:
            raise serializers.ValidationError("Expected valid answer text within the character limit.") from None


class SubmitPracticeSerializer(StartPracticeSerializer):
    answer_text = AnswerField()


class DeletePracticeSerializer(_StrictRequestSerializer):
    pass


class PracticePreviewSerializer(serializers.Serializer):
    topic_id = serializers.CharField(read_only=True)
    task_id = serializers.CharField(read_only=True)
    practice_kind = serializers.CharField(read_only=True)
    language = serializers.CharField(read_only=True)
    title = serializers.CharField(read_only=True)
    can_start = serializers.BooleanField(read_only=True)
    blocked_by = serializers.ListField(child=serializers.CharField(), read_only=True)
    normalization_mode = serializers.CharField(read_only=True)
    answer_max_length = serializers.IntegerField(read_only=True)


class PublicTaskSerializer(serializers.Serializer):
    practice_kind = serializers.CharField(read_only=True)
    source_type = serializers.CharField(read_only=True)
    title = serializers.CharField(read_only=True)
    prompt = serializers.CharField(read_only=True)
    source_text = serializers.CharField(read_only=True)
    input_data = serializers.CharField(read_only=True)
    environment = serializers.CharField(read_only=True)
    output_spec = serializers.CharField(read_only=True)
    normalization_mode = serializers.CharField(read_only=True)
    answer_max_length = serializers.IntegerField(read_only=True)


class PendingPracticeSerializer(serializers.Serializer):
    submission_id = serializers.CharField(source="pk", read_only=True)
    topic_id = serializers.CharField(source="task_snapshot.topic_id", read_only=True)
    task_id = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    language = serializers.SerializerMethodField()
    task = serializers.SerializerMethodField()

    def get_language(self, obj):
        return self.context["language"]

    def get_task(self, obj):
        snapshot = obj.task_snapshot
        public = {name: snapshot[name] for name in (
            "practice_kind", "source_type", "source_text", "input_data", "environment", "output_spec",
            "normalization_mode", "answer_max_length",
        )}
        public.update(snapshot["translations"][self.context["language"]])
        return PublicTaskSerializer(public).data


class SubmittedPracticeSerializer(serializers.Serializer):
    submission_id = serializers.CharField(source="pk", read_only=True)
    topic_id = serializers.CharField(source="task_snapshot.topic_id", read_only=True)
    task_id = serializers.CharField(read_only=True)
    task_title = serializers.SerializerMethodField()
    status = serializers.CharField(read_only=True)
    submitted_language = serializers.CharField(read_only=True)
    submitted_at = serializers.DateTimeField(format="iso-8601", read_only=True)
    result = serializers.SerializerMethodField()

    def get_task_title(self, obj):
        return obj.task_snapshot["translations"][obj.submitted_language]["title"]

    def get_result(self, obj):
        return {"verdict": obj.verdict}
