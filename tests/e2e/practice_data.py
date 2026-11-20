"""Synthetic practice data; only the E2E fixture's explicitly owned temporary DB."""

import json
import os
from pathlib import Path
import re
import sys


def main():
    database, action, *ids = sys.argv[1:]
    if not re.fullmatch(r"test_qil006_[0-9a-f]{32}", database) or os.environ.get("POSTGRES_DB") != database:
        raise RuntimeError("Expected the owning temporary database")
    if action not in {"create", "cleanup", "draft", "empty", "info"} or any(not re.fullmatch(r"[1-9][0-9]*", value) for value in ids):
        raise RuntimeError("Invalid practice fixture action")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    import django
    django.setup()
    from django.db import connection, transaction
    from apps.learning.models import Topic, TopicStatus, TopicTranslation
    from apps.learning.changes import edit_topics
    from apps.learning.tests.test_content import create_bilingual_topic
    from apps.assessments.models import Attempt, TopicProgress
    from apps.practice.models import PracticeSubmission, PracticeTask, TopicPractice
    from apps.practice.tests.factories import create_practice, write

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        if cursor.fetchone()[0] != database:
            raise RuntimeError("Wrong fixture database")
    with transaction.atomic():
        if action == "create":
            if ids:
                raise RuntimeError("Create cannot target existing content")
            rows = []
            for index in range(3):
                topic = create_bilingual_topic()
                with edit_topics({topic.pk: topic.revision}, using="default"):
                    for language in ("ru", "en"):
                        TopicTranslation.objects.filter(topic=topic, language=language).update(
                            title=("Python: практика " if language == "ru" else "Python: practice ") + str(index + 1),
                            article_body="Изучите выражение и определите его вывод." if language == "ru" else "Study the expression and determine its output.",
                        )
                topic.refresh_from_db()
                if index != 1:
                    task = create_practice(topic, publish=index == 0, expected_answer="2")
                    write(task, topic, source_text="print(1 + 1)\n# <script>window.qilPracticeInjected=true</script>")
                    for language in ("ru", "en"):
                        write(task.translations.get(language=language), topic,
                              title="Практика: вывод Python" if language == "ru" else "Practice: Python output",
                              prompt="Введите точный вывод программы." if language == "ru" else "Enter the exact program output.")
                topic.status = TopicStatus.PUBLISHED
                topic.save(update_fields=("status",))
                rows.append(str(topic.pk))
            result = {"enabled": rows[0], "disabled": rows[1], "draft_task": rows[2], "ids": rows}
        else:
            if not ids or len(set(ids)) != len(ids):
                raise RuntimeError("Expected owned topic identities")
            topics = list(Topic.objects.filter(pk__in=ids))
            if len(topics) != len(ids):
                raise RuntimeError("Missing owned topic")
            if action == "cleanup":
                PracticeSubmission.objects.filter(task__topic_practice__topic_id__in=ids).delete()
                Attempt.objects.filter(topic_id__in=ids).delete()
                TopicProgress.objects.filter(topic_id__in=ids).delete()
                for topic in topics:
                    task = PracticeTask.objects.filter(topic_practice__topic=topic).first()
                    if task:
                        task.delete(expected_revision=topic.revision)
                        topic.refresh_from_db()
                    config = TopicPractice.objects.filter(topic=topic).first()
                    if config:
                        config.delete(expected_revision=topic.revision)
                        topic.refresh_from_db()
                    topic.delete()
                result = {"cleanup": "PASS"}
            elif action == "draft":
                for topic in topics:
                    topic.status = TopicStatus.DRAFT
                    topic.save(update_fields=("status",))
                result = {"draft": "PASS"}
            elif action == "empty":
                for topic in topics:
                    task = PracticeTask.objects.get(topic_practice__topic=topic)
                    write(task, topic, expected_answer="", source_text="pass", normalization_mode="lf_exact_v1")
                result = {"empty": "PASS"}
            else:
                result = {"submission_count": PracticeSubmission.objects.filter(task__topic_practice__topic_id__in=ids).count(),
                          "attempt_count": Attempt.objects.filter(topic_id__in=ids).count(),
                          "read_count": TopicProgress.objects.filter(topic_id__in=ids).count()}
    connection.close()
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("PRACTICE_FIXTURE=FAIL " + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
