from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from kern import tenancy
from notes import search


class Command(BaseCommand):
    help = "Rebuild every user's full-text search index from scratch."

    def handle(self, *args, **options):
        for user in User.objects.all():
            with tenancy.use(user.id):
                with tenancy.atomic():
                    n = search.reindex_all()
            self.stdout.write(f"{user.username}: indexed {n} objects.")
