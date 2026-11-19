"""Run the CI pipelines queued by pushes and the UI: ``python manage.py ci_worker``.

Runs as its own service next to the web server (docker-compose.yml "ci").
"""
import logging
import signal

from django.core.management.base import BaseCommand

from notes.ci import Worker


class Command(BaseCommand):
    help = "Run queued CI runs of every user's git repositories."

    def handle(self, *args, **opts):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        w = Worker()

        def stop(*_):
            w.stopping.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        w.run_forever()
