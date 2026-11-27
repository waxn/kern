"""Try the built-in spam rules (mail/spamfilter.py) on mail already in the Inbox.

    python manage.py spam_sweep --user alice                  # dry run: counts and examples, moves nothing
    python manage.py spam_sweep --user alice --days 30 -v 2   # a longer window, every message listed
    python manage.py spam_sweep --user alice --apply          # move what the rules catch to Junk

New mail is filtered as it arrives; this is for checking the rules against your own real mail first,
and for cleaning up what is already there. Read the dry run before you --apply it.
"""
from collections import Counter
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from kern import tenancy
from mail import actions, spamfilter, store
from mail.identity import my_addresses
from mail.models import FolderRole, Message
from mail.parsing import parse_message


class Command(BaseCommand):
    help = "Dry-run (or apply) the built-in spam rules on recent Inbox mail."

    def add_arguments(self, parser):
        parser.add_argument("--user", help="Username (default: every user).")
        parser.add_argument("--days", type=int, default=14, help="How far back to look (default 14).")
        parser.add_argument("--apply", action="store_true", help="Move the matches to Junk. Without it nothing changes.")

    def handle(self, *args, **opts):
        users = User.objects.order_by("id")
        if opts["user"]:
            users = users.filter(username__iexact=opts["user"])
            if not users:
                raise CommandError("No such user.")
        for user in users:
            with tenancy.use(user.id):
                self.sweep(user.username, opts["days"], opts["apply"], opts["verbosity"])

    def sweep(self, name: str, days: int, apply: bool, verbosity: int) -> None:
        me = my_addresses()
        since = timezone.now() - timedelta(days=days)
        qs = (Message.objects.filter(folder__role=FolderRole.INBOX, sort_date__gte=since)
              .select_related("folder").order_by("sort_date"))
        total, hits, caught = 0, Counter(), []
        for m in qs.iterator(chunk_size=200):
            total += 1
            headers = parse_message(store.get(m.blob_id)).headers
            got = spamfilter.judge(m, headers, me)
            if got:
                hits[got[0]] += 1
                caught.append((m, got))
        self.stdout.write(f"{name}: looked at {total} Inbox messages from the last {days} days; "
                          f"{len(caught)} would go to Junk ({', '.join(f'{k} {v}' for k, v in sorted(hits.items())) or 'none'}).")
        for m, (rule, why) in caught[: 200 if verbosity > 1 else 15]:
            self.stdout.write(f"  [{rule}] {m.from_addr}  {m.subject[:70]!r}")
        if not apply:
            if caught:
                self.stdout.write("Nothing moved. Add --apply to move these to Junk.")
            return
        for m, (rule, why) in caught:
            spamfilter.record(m, rule, why)
        moved = actions.move_messages([m for m, _ in caught], actions.role_folder(FolderRole.JUNK)) if caught else []
        self.stdout.write(self.style.SUCCESS(f"Moved {len(moved)} messages to Junk."))
