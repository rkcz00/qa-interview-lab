from django.db import transaction
from django.http import Http404

from .models import Topic, TopicStatus, require_translations


def legacy_article_body(sections):
    if len(sections) == 1:
        return sections[0]["article_body"]
    return "\n\n".join(item["title"] + "\n\n" + item["article_body"] for item in sections)


def read_sections(topic_id, language):
    # All content writers use this same root lock. Separate SELECTs therefore
    # cannot combine titles/sections from different revisions at READ COMMITTED.
    with transaction.atomic():
        topic = Topic.objects.select_for_update().filter(pk=topic_id, status=TopicStatus.PUBLISHED).first()
        if topic is None:
            raise Http404
        titles = list(topic.translations.all())
        require_translations(titles, fields=("title",), label="Тема")
        sections = list(topic.sections.filter(status=TopicStatus.PUBLISHED).prefetch_related("translations"))
        if not sections:
            raise RuntimeError("Published topic has no published sections")
        public = []
        for section in sections:
            section.validate_for_publication()
            translation = next(item for item in section.translations.all() if item.language == language)
            public.append({
                "section_id": str(section.pk), "position": section.position,
                "title": translation.title, "article_body": translation.article_body,
            })
        return {
            "topic_id": str(topic.pk), "title": next(item.title for item in titles if item.language == language),
            "language": language, "sections": public,
        }
