from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS

from apps.assessments.section_provenance_v1 import SectionProvenanceRequired, verified_origins


class Command(BaseCommand):
    help = "Read-only verification of reviewed migration-time section origins; never guesses or writes a mapping."

    def add_arguments(self, parser):
        parser.add_argument("--database", default=DEFAULT_DB_ALIAS)
        parser.add_argument("--manifest")
        parser.add_argument("--sha256")

    def handle(self, *args, **options):
        try:
            origins = verified_origins(apps, options["database"], path=options["manifest"], digest=options["sha256"])
        except SectionProvenanceRequired as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(f"PROVENANCE=PASS legacy_topics={len(origins)}")
