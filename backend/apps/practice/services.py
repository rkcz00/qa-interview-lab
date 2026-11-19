from .checking import ANSWER_MAX_LENGTH


def build_snapshot(task, topic):
    task.validate_for_publication()
    return {
        "topic_id": str(topic.pk), "task_id": str(task.pk), "source_revision": topic.revision,
        "practice_kind": task.topic_practice.practice_kind, "source_type": task.source_type,
        "source_text": task.source_text, "input_data": task.input_data,
        "environment": task.environment, "output_spec": task.output_spec,
        "translations": {row.language: {"title": row.title, "prompt": row.prompt} for row in task.translations.all()},
        "expected_answer": task.expected_answer, "normalization_mode": task.normalization_mode,
        "answer_max_length": ANSWER_MAX_LENGTH,
    }
