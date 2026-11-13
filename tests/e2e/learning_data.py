"""Seed/inspect only the owning E2E database; never a development database."""

import json
import os
from pathlib import Path
import re
import sys


def main():
    database, action, *ids = sys.argv[1:]
    if not re.fullmatch(r"test_qil006_[0-9a-f]{32}", database) or os.environ.get("POSTGRES_DB") != database:
        raise RuntimeError("Expected the owning disposable database")
    if action not in {"create", "cleanup", "draft", "revise_draft", "info"} or any(not value.isascii() or not value.isdigit() for value in ids):
        raise RuntimeError("Invalid fixture action")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    import django
    django.setup()
    from django.db import connection, transaction
    from apps.learning.models import Language, Term, TermTranslation, Topic, TopicStatus, TopicTranslation
    from apps.learning.changes import edit_topics
    from apps.learning.tests.test_content import create_bilingual_topic
    from apps.assessments.models import Attempt, AttemptStatus, ChoiceTranslation, QuestionTranslation, TopicProgress

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        if cursor.fetchone()[0] != database:
            raise RuntimeError("Wrong fixture database")
    with transaction.atomic():
        if action == "create":
            topics = []
            for index in range(2):
                topic = create_bilingual_topic()
                for language in Language.values:
                    TopicTranslation.objects.filter(topic=topic, language=language).update(
                        title=("Основы тестирования" if index == 0 else "Автоматизация") if language == "ru" else
                              ("Testing foundations" if index == 0 else "Automation"),
                        article_body=("Проверяйте требования и риски.\n\n" if language == "ru" else "Check requirements and risks.\n\n") +
                                     '<script>window.qilInjected=true</script>\n<img src="missing" onerror="window.qilInjected=true">',
                    )
                extra = Term.objects.create(topic=topic, position=10)
                for language in Language.values:
                    TermTranslation.objects.create(term=extra, language=language,
                        name="Оракул" if language == "ru" else "Oracle", definition="Источник ожиданий" if language == "ru" else "Expected behavior source")
                    for term in topic.terms.exclude(pk=extra.pk):
                        TermTranslation.objects.filter(term=term, language=language).update(
                            name=("Риск" if term.position == 10 else "Качество") if language == "ru" else
                                 ("Risk" if term.position == 10 else "Quality"),
                            definition="Учитывайте контекст." if language == "ru" else "Consider the context.",
                        )
                topic.status = TopicStatus.PUBLISHED
                topic.save(update_fields=("status",))
                topics.append(str(topic.pk))
            draft = Topic.objects.create()
            TopicTranslation.objects.create(topic=draft, language="ru", title="Невидимый черновик", article_body="Draft content")
            result = {"first": topics[0], "second": topics[1], "draft": str(draft.pk), "ids": [*topics, str(draft.pk)]}
        elif action == "cleanup":
            Attempt.objects.filter(topic_id__in=ids).delete()
            TopicProgress.objects.filter(topic_id__in=ids).delete()
            Topic.objects.filter(pk__in=ids).delete()
            result = {"cleanup": "PASS"}
        elif action == "draft":
            for topic in Topic.objects.filter(pk__in=ids):
                topic.status = TopicStatus.DRAFT
                topic.save(update_fields=("status",))
            result = {"draft": "PASS"}
        elif action == "revise_draft":
            topics = list(Topic.objects.filter(pk__in=ids))
            if len(topics) != len(set(ids)) or any(topic.status != TopicStatus.DRAFT for topic in topics):
                raise RuntimeError("Revision requires owned Draft topics")
            with edit_topics({topic.pk: topic.revision for topic in topics}, using="default") as locked:
                for topic in locked.values():
                    for language in Language.values:
                        revised = "Изменено после начала попытки" if language == "ru" else "Revised after the attempt started"
                        TopicTranslation.objects.filter(topic=topic, language=language).update(title=revised, article_body=revised)
                        QuestionTranslation.objects.filter(question__topic=topic, language=language).update(text=revised)
                        ChoiceTranslation.objects.filter(choice__question__topic=topic, language=language).update(text=revised)
            result = {"revised": "PASS"}
        else:
            result = {"read_count": TopicProgress.objects.filter(topic_id__in=ids).count(),
                      "attempt_count": Attempt.objects.filter(topic_id__in=ids).count(),
                      "submitted_count": Attempt.objects.filter(topic_id__in=ids, status=AttemptStatus.SUBMITTED).count()}
    connection.close()
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("LEARNING_FIXTURE=FAIL " + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
