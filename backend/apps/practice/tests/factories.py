from apps.learning.models import Language, TopicStatus
from apps.practice.models import PracticeTask, PracticeTaskTranslation, TopicPractice


def write(obj, topic, **fields):
    topic.refresh_from_db()
    for name, value in fields.items():
        setattr(obj, name, value)
    obj.save(expected_revision=topic.revision)
    topic.refresh_from_db()
    return obj


def create_practice(topic, *, publish=True, expected_answer="text", mode="lf_trim_outer_v1", source_type="python"):
    config = write(TopicPractice(topic=topic), topic)
    task = write(PracticeTask(
        topic_practice=config, source_type=source_type, source_text="print('text')",
        input_data="", environment="Python 3.14.2", output_spec="stdout text",
        expected_answer=expected_answer, normalization_mode=mode,
    ), topic)
    for language in Language.values:
        write(PracticeTaskTranslation(task=task, language=language, title=f"{language} task", prompt=f"{language} prompt"), topic)
    if publish:
        write(task, topic, status=TopicStatus.PUBLISHED)
    return task
