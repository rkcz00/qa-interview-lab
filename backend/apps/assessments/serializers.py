from rest_framework import serializers
from rest_framework.settings import api_settings

from apps.learning.models import Language

from .scoring import result_from_counts


class StartAttemptSerializer(serializers.Serializer):
    language = serializers.ChoiceField(choices=Language.values)

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) != set(self.fields):
            raise serializers.ValidationError({
                api_settings.NON_FIELD_ERRORS_KEY: ["Unexpected attempt request fields."],
            })
        return super().to_internal_value(data)


class SubmitAttemptSerializer(StartAttemptSerializer):
    answers = serializers.ListField()


class _LocalizedItemSerializer(serializers.Serializer):
    position = serializers.IntegerField(read_only=True)
    text = serializers.SerializerMethodField()

    def get_text(self, item):
        return item["texts"][self.context["language"]]


class PublicChoiceSerializer(_LocalizedItemSerializer):
    choice_id = serializers.CharField(read_only=True)


class PublicQuestionSerializer(_LocalizedItemSerializer):
    question_id = serializers.CharField(read_only=True)
    question_type = serializers.CharField(read_only=True)
    choices = PublicChoiceSerializer(many=True, read_only=True)


class PendingAttemptSerializer(serializers.Serializer):
    attempt_id = serializers.CharField(source="pk", read_only=True)
    topic_id = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    language = serializers.SerializerMethodField()
    questions = PublicQuestionSerializer(source="content_snapshot.questions", many=True, read_only=True)

    def get_language(self, attempt):
        return self.context["language"]


class SubmittedAttemptSerializer(serializers.Serializer):
    attempt_id = serializers.CharField(source="pk", read_only=True)
    topic_id = serializers.CharField(read_only=True)
    topic_title = serializers.SerializerMethodField()
    status = serializers.CharField(read_only=True)
    submitted_language = serializers.CharField(read_only=True)
    submitted_at = serializers.DateTimeField(format="iso-8601", read_only=True)
    result = serializers.SerializerMethodField()

    def get_topic_title(self, attempt):
        return attempt.content_snapshot["topic_titles"][attempt.submitted_language]

    def get_result(self, attempt):
        return result_from_counts(attempt.correct_count, attempt.total_count)
