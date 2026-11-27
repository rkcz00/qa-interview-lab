from rest_framework import serializers
from rest_framework.settings import api_settings
from uuid import UUID

from apps.learning.models import Language

from .scoring import result_from_counts


class _StrictRequestSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) != set(self.fields):
            raise serializers.ValidationError({
                api_settings.NON_FIELD_ERRORS_KEY: ["Unexpected request fields."],
            })
        return super().to_internal_value(data)


class StartAttemptSerializer(_StrictRequestSerializer):
    language = serializers.ChoiceField(choices=Language.values)


class SubmitAttemptSerializer(StartAttemptSerializer):
    answers = serializers.ListField()


class InitialSubmitAttemptSerializer(SubmitAttemptSerializer):
    def to_internal_value(self, data):
        if isinstance(data, dict) and data.keys() == {"language"}:
            data = {**data, "answers": []}
        return super().to_internal_value(data)


class ReadTopicSerializer(_StrictRequestSerializer):
    pass


class ResetProgressSerializer(_StrictRequestSerializer):
    confirmation = serializers.ChoiceField(choices=("reset_all_progress",))
    request_id = serializers.CharField(max_length=36, trim_whitespace=False)

    def validate_request_id(self, value):
        try:
            identifier = UUID(value)
        except ValueError:
            raise serializers.ValidationError("Expected a canonical UUID v4.") from None
        if identifier.version != 4 or str(identifier) != value:
            raise serializers.ValidationError("Expected a canonical UUID v4.")
        return identifier


class ResultSerializer(serializers.Serializer):
    correct_count = serializers.IntegerField(read_only=True)
    total_count = serializers.IntegerField(read_only=True)
    percentage = serializers.FloatField(read_only=True)


class ProgressSerializer(serializers.Serializer):
    topic_id = serializers.CharField(read_only=True)
    article_read_at = serializers.DateTimeField(format="iso-8601", allow_null=True, read_only=True)
    best_result = ResultSerializer(allow_null=True, read_only=True)
    mastered = serializers.BooleanField(read_only=True)


class ReadingStateSerializer(serializers.Serializer):
    total_sections = serializers.IntegerField(read_only=True)
    read_sections = serializers.IntegerField(read_only=True)
    is_read = serializers.BooleanField(read_only=True)
    completion_contribution = serializers.FloatField(read_only=True)


class SectionSummarySerializer(serializers.Serializer):
    section_id = serializers.CharField(read_only=True)
    position = serializers.IntegerField(read_only=True)
    title = serializers.CharField(read_only=True)
    read_at = serializers.DateTimeField(format="iso-8601", allow_null=True, read_only=True)


class TopicReadingSerializer(serializers.Serializer):
    topic_id = serializers.CharField(read_only=True)
    title = serializers.CharField(read_only=True)
    language = serializers.CharField(read_only=True)
    progress_generation = serializers.CharField(read_only=True)
    reading = ReadingStateSerializer(read_only=True)
    sections = SectionSummarySerializer(many=True, read_only=True)


class SectionBodySerializer(SectionSummarySerializer):
    article_body = serializers.CharField(read_only=True)


class SectionArticleSerializer(serializers.Serializer):
    topic_id = serializers.CharField(read_only=True)
    topic_title = serializers.CharField(read_only=True)
    language = serializers.CharField(read_only=True)
    progress_generation = serializers.CharField(read_only=True)
    section = SectionBodySerializer(read_only=True)
    previous_section_id = serializers.CharField(allow_null=True, read_only=True)
    next_section_id = serializers.CharField(allow_null=True, read_only=True)
    reading = ReadingStateSerializer(read_only=True)


class SectionReadSerializer(serializers.Serializer):
    topic_id = serializers.CharField(read_only=True)
    section_id = serializers.CharField(read_only=True)
    read_at = serializers.DateTimeField(format="iso-8601", read_only=True)
    progress_generation = serializers.CharField(read_only=True)
    reading = ReadingStateSerializer(read_only=True)


class TestCompletionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=("unattempted", "failed", "passed"), read_only=True)
    best_result = ResultSerializer(allow_null=True, read_only=True)


class PracticeCompletionSerializer(serializers.Serializer):
    task_id = serializers.CharField(read_only=True)
    status = serializers.ChoiceField(choices=("unattempted", "failed", "passed"), read_only=True)


class TopicCompletionSerializer(serializers.Serializer):
    topic_id = serializers.CharField(read_only=True)
    article_read_at = serializers.DateTimeField(format="iso-8601", allow_null=True, read_only=True)
    test = TestCompletionSerializer(read_only=True)
    practice = PracticeCompletionSerializer(allow_null=True, read_only=True)
    completion_progress = serializers.FloatField(read_only=True)
    mastered = serializers.BooleanField(read_only=True)


class CompletionProgressSerializer(serializers.Serializer):
    progress_generation = serializers.CharField(read_only=True)
    overall_completion_progress = serializers.FloatField(read_only=True)
    topics = TopicCompletionSerializer(many=True, read_only=True)


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
