from rest_framework import serializers

from .models import Language


class ContentLanguageSerializer(serializers.Serializer):
    language = serializers.ChoiceField(choices=Language.values, default=Language.RU)


def language_from_query(query):
    if set(query) - {"language"} or len(query.getlist("language")) > 1:
        raise serializers.ValidationError("Expected only one language parameter.")
    serializer = ContentLanguageSerializer(data=query.dict())
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data["language"]


class TopicSummarySerializer(serializers.Serializer):
    topic_id = serializers.CharField(read_only=True)
    title = serializers.CharField(read_only=True)


class ArticleSerializer(TopicSummarySerializer):
    language = serializers.CharField(read_only=True)
    article_body = serializers.CharField(read_only=True)


class TermSerializer(serializers.Serializer):
    term_id = serializers.CharField(read_only=True)
    position = serializers.IntegerField(source="term.position", read_only=True)
    language = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    definition = serializers.CharField(read_only=True)
