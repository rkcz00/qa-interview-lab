"""Explicit, additive local demo loader. Does not load .env or create accounts."""

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests/fixtures/qa_interview_demo.json"


class DemoContentError(ValueError):
    pass


def demo_data():
    return json.loads(DATA.read_text(encoding="utf-8"))


def create_demo_content(database, *, confirmed=False):
    from django.db import connection, transaction
    from apps.assessments.models import Choice, ChoiceTranslation, Question, QuestionTranslation
    from apps.learning.changes import edit_topics
    from apps.learning.models import Term, TermTranslation, Topic, TopicTranslation

    config = connection.settings_dict
    if not confirmed or not database or database == "postgres" or config["NAME"] != database:
        raise DemoContentError("Explicit confirmation and the configured database name are required")
    if connection.vendor != "postgresql" or config["HOST"] not in {"127.0.0.1", "localhost", "::1"}:
        raise DemoContentError("Only local PostgreSQL is supported")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        if cursor.fetchone()[0] != database:
            raise DemoContentError("Database identity check failed")

    data = demo_data()
    with transaction.atomic():
        # Serialize only simultaneous loads of this seed, without touching existing rows.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("qil024-demo-content",))
        if TopicTranslation.objects.filter(title__in=[item["title"] for item in data["translations"].values()]).exists():
            raise DemoContentError("Demo title already exists; no data was changed")
        topic = Topic.objects.create()
        with edit_topics({topic.pk: topic.revision}, using=connection.alias):
            for language, fields in data["translations"].items():
                TopicTranslation.objects.create(topic=topic, language=language, **fields).full_clean()
            for item in data["terms"]:
                term = Term.objects.create(topic=topic, position=item["position"])
                term.full_clean()
                for language, fields in item["translations"].items():
                    TermTranslation.objects.create(term=term, language=language, **fields).full_clean()
            for item in data["questions"]:
                question = Question.objects.create(topic=topic, position=item["position"], question_type=item["question_type"])
                question.full_clean()
                for language, text in item["translations"].items():
                    QuestionTranslation.objects.create(question=question, language=language, text=text).full_clean()
                for option in item["choices"]:
                    choice = Choice.objects.create(question=question, position=option["position"], is_correct=option["is_correct"])
                    choice.full_clean()
                    for language, text in option["translations"].items():
                        ChoiceTranslation.objects.create(choice=choice, language=language, text=text).full_clean()
            topic.validate_for_publication()
        topic.refresh_from_db()
    return topic


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create one complete demo Draft; never overwrite existing content")
    parser.add_argument("--database", required=True, help="Exact local database already configured in the process")
    parser.add_argument("--confirm-create", action="store_true", required=True)
    arguments = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    from django.core.exceptions import ImproperlyConfigured, ValidationError
    from django.db import DatabaseError

    try:
        django.setup()
        topic = create_demo_content(arguments.database, confirmed=arguments.confirm_create)
    except (DemoContentError, ImproperlyConfigured, ValidationError, DatabaseError):
        print("DEMO=FAIL configuration, duplicate title or incomplete content; no partial seed was saved")
        return 1
    print(f"DEMO=PASS topic_id={topic.pk} status=draft; no accounts or existing content changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
