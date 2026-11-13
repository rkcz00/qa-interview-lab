"""Private setup and safe inspection restricted to the fixture's disposable database."""

import json
import os
from pathlib import Path
import re
import sys
from uuid import uuid4


def main():
    database, action = sys.argv[1:]
    if not re.fullmatch(r"test_qil006_[0-9a-f]{32}", database) or os.environ.get("POSTGRES_DB") != database:
        raise RuntimeError("Disposable database identity is required")
    if action not in {"editor", "inspect", "cleanup"}:
        raise RuntimeError("Unknown action")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    import django
    django.setup()
    from django.contrib.admin.models import LogEntry
    from django.contrib.auth.models import Group
    from django.db import connection, transaction
    from apps.accounts.models import User
    from apps.assessments.models import Attempt, Choice, ChoiceTranslation, Question, QuestionTranslation, TopicProgress
    from apps.learning.models import Term, TermTranslation, Topic, TopicTranslation

    payload = json.load(sys.stdin)
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        if cursor.fetchone()[0] != database:
            raise RuntimeError("Wrong fixture database")
    content = (Topic, TopicTranslation, Term, TermTranslation, Question, QuestionTranslation, Choice, ChoiceTranslation)
    if action == "editor":
        if set(payload) != {"password"} or not isinstance(payload["password"], str) or not payload["password"]:
            raise RuntimeError("Invalid private setup")
        user = User.objects.create_user("editor-" + uuid4().hex + "@example.invalid", payload["password"], is_staff=True)
        group = Group.objects.get(name="Content Admin")
        user.groups.add(group)
        expected = {(model._meta.app_label, f"{permission}_{model._meta.model_name}")
            for model in content for permission in ("view", "add", "change", "delete")}
        if user.is_superuser or user.user_permissions.exists() or set(group.permissions.values_list("content_type__app_label", "codename")) != expected:
            raise RuntimeError("Content Admin must have exactly the agreed content permissions")
        result = {"user_id": str(user.pk), "email": user.email, "group_id": str(group.pk)}
    else:
        if set(payload) != {"topic_id"} or not re.fullmatch(r"[0-9]+", payload["topic_id"]):
            raise RuntimeError("Expected a topic identity")
        topic = Topic.objects.get(pk=payload["topic_id"])
        if action == "cleanup":
            with transaction.atomic():
                Attempt.objects.filter(topic=topic).delete()
                TopicProgress.objects.filter(topic=topic).delete()
                topic.delete()
            result = {"cleanup": "PASS"}
        else:
            result = {"status": topic.status, "revision": topic.revision, "audit_count": LogEntry.objects.count(),
                "model_counts": [Topic.objects.filter(pk=topic.pk).count(), topic.translations.count(),
                    topic.terms.count(), TermTranslation.objects.filter(term__topic=topic).count(), topic.questions.count(),
                    QuestionTranslation.objects.filter(question__topic=topic).count(), Choice.objects.filter(question__topic=topic).count(),
                    ChoiceTranslation.objects.filter(choice__question__topic=topic).count()]}
    connection.close()
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("CONTENT_ADMIN_FIXTURE=FAIL; no private data was logged", file=sys.stderr)
        raise SystemExit(1)
