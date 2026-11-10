from contextlib import contextmanager

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Topic


class ContentWriteError(ValidationError):
    pass


class EditConflict(ContentWriteError):
    status = 409
    error_code = "edit_conflict"

    def __init__(self):
        super().__init__("Тема изменилась. Откройте актуальную форму и повторите правку.", code=self.error_code)


class IncompleteContent(ContentWriteError):
    status = 400
    error_code = "incomplete_content"


class InvalidRevision(ContentWriteError):
    status = 400
    error_code = "invalid_revision"

    def __init__(self):
        super().__init__("Откройте форму с актуальной ревизией темы.", code=self.error_code)


@contextmanager
def edit_topics(expected_revisions, *, using):
    """Lock and check all affected topics before allowing a content write."""
    with transaction.atomic(using=using):
        locked = Topic.objects.using(using).select_for_update().filter(pk__in=expected_revisions).order_by("pk")
        topics = {topic.pk: topic for topic in locked}
        if {pk: topic.revision for pk, topic in topics.items()} != expected_revisions:
            raise EditConflict()

        yield topics

        for topic in topics.values():
            if topic.pk is not None:  # A deleted topic has no revision to store.
                try:
                    topic._save_content_revision(using)
                except ValidationError as error:
                    raise IncompleteContent(error) from error
