"""Sync every connected mailbox: ``python manage.py mail_worker``.

Runs as its own service next to the web server (docker-compose.yml "mail").
"""
import logging
import signal

from django.core.management.base import BaseCommand

from mail.supervisor import Supervisor


class Command(BaseCommand):
    help = "Run the mail sync workers (one per user with a connected mailbox)."

    def handle(self, *args, **opts):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        sup = Supervisor()

        def stop(*_):
            sup.stopping.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        sup.run_forever()
