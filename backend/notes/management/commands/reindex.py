from django.core.management.base import BaseCommand
from django.db import transaction

from notes import search


class Command(BaseCommand):
    help = "Rebuild the full-text search index from scratch."

    def handle(self, *args, **options):
        with transaction.atomic():
            n = search.reindex_all()
        self.stdout.write(f"Indexed {n} objects.")
