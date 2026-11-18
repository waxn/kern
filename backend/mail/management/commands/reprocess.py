from django.core.management.base import BaseCommand

from mail import store
from mail.models import Message
from mail.parsing import parse_message
from mail.pipeline import run_pipeline
from mail.threads import refresh_thread


class Command(BaseCommand):
    help = "Re-run pipeline stages (e.g. after editing risk rules) over stored mail."

    def add_arguments(self, parser):
        parser.add_argument("--stage", action="append", help="Stage name (repeatable). Default: all.")
        parser.add_argument("--force", action="store_true", help="Re-run even if the stage version is current.")
        parser.add_argument("--folder", help="Only this folder name.")

    def handle(self, *args, **opts):
        only = set(opts["stage"] or []) or None
        force = opts["force"] or bool(only)
        qs = Message.objects.select_related("folder").order_by("sort_date")
        if opts["folder"]:
            qs = qs.filter(folder__name=opts["folder"])
        n = 0
        for m in qs.iterator(chunk_size=200):
            pm = parse_message(store.get(m.blob_id))
            run_pipeline(m, pm, only=only, force=force)
            refresh_thread(m.thread_id)
            n += 1
            if n % 500 == 0:
                self.stdout.write(f"{n} messages...")
        self.stdout.write(self.style.SUCCESS(f"Reprocessed {n} messages."))
