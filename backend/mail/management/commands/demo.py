"""Offline demo for one Kern user: fills an in-memory mailbox with the messy
test corpus and syncs it as that user (no mail server needed). Sent mail is
kept in memory. The user needs two-factor sign-in to open mail.

    python manage.py demo --user alice
"""
import signal
import time
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from kern import secretbox, tenancy
from mail import account
from mail.imap.fake import FakeMailServer, FakeSender
from mail.models import MailAccount
from mail.testing import corpus
from mail.worker import Worker


class Command(BaseCommand):
    help = "Run a mail worker for one user against an in-memory demo mailbox."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True)

    def handle(self, *args, **opts):
        user = User.objects.filter(username__iexact=opts["user"]).first()
        if not user:
            raise CommandError("No such user.")
        server = FakeMailServer(uidvalidity_start=int(time.time()) % 2_000_000_000)
        corpus.BASE = timezone.now() - timedelta(hours=166)
        for item in corpus.build():
            server.deliver(item.folder, item.raw, item.flags, item.date)
        with tenancy.use(user.id):
            MailAccount.objects.update_or_create(pk=1, defaults={
                "address": corpus.ME, "from_name": "Demo", "imap_host": "demo.invalid", "smtp_host": "demo.invalid",
                "authserv_id": corpus.AUTHSERV, "enabled": False,  # the real worker leaves it alone
                "password_enc": secretbox.encrypt("demo")})
            account.invalidate()
            # The demo account counts as connected for the app, without the supervisor picking it up.
            MailAccount.objects.filter(pk=1).update(enabled=True, imap_host="", smtp_host="")
            account.invalidate()
            worker = Worker(lambda: server, FakeSender(server), use_idle=False, require_config=False)

            def stop(*_):
                worker.shutdown()

            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            self.stdout.write(f"Demo mailbox for {user.username} ({corpus.ME}). Ctrl+C stops it.")
            worker.run_forever()
