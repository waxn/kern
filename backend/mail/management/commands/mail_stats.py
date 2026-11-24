"""Update, rebuild or check the stored mail stats (mail/stats.py) for one user or all users.

    python manage.py mail_stats --user alice            # bring the totals up to date now
    python manage.py mail_stats --user alice --rebuild  # throw them away and count everything again
    python manage.py mail_stats --user alice --check    # compare with an on-demand count

The mail worker keeps the totals up to date by itself every night. Rebuild when they have
drifted: old mail deleted or moved to Trash long after it arrived, or a new "send as" address
that changes which mail counts as sent.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from kern import tenancy
from mail import stats

COMPARED = ("received", "sent", "readRate", "newsletterShare", "withFiles", "replyMedianMinutes", "replies",
            "series", "hours", "weekdays", "topDomains")


class Command(BaseCommand):
    help = "Update, rebuild or check the stored mail stats."

    def add_arguments(self, parser):
        parser.add_argument("--user", help="Username (default: every user).")
        parser.add_argument("--rebuild", action="store_true", help="Count everything again from scratch.")
        parser.add_argument("--check", action="store_true", help="Compare the stored totals with a fresh count.")
        parser.add_argument("--days", type=int, default=90, help="Window for --check (default 90).")

    def handle(self, *args, **opts):
        users = User.objects.order_by("id")
        if opts["user"]:
            users = users.filter(username__iexact=opts["user"])
            if not users:
                raise CommandError("No such user.")
        for user in users:
            with tenancy.use(user.id):
                if opts["rebuild"]:
                    stats.rebuild()
                    self.stdout.write(f"{user.username}: rebuilt.")
                elif not opts["check"]:
                    stats.run(force=True)
                    self.stdout.write(f"{user.username}: up to date.")
                if opts["check"]:
                    self.check_user(user, opts["days"])

    def check_user(self, user, days):
        stored = stats.compute(days)
        if not stored["ready"]:
            self.stdout.write(f"{user.username}: no stored totals yet.")
            return
        from django.utils.dateparse import parse_datetime

        fresh = stats.live(days, now=parse_datetime(stored["updated"]))
        off = [k for k in COMPARED if stored[k] != fresh[k]]
        if [s["addr"] for s in stored["topSenders"]] != [s["addr"] for s in fresh["topSenders"]]:
            off.append("topSenders")
        if off:
            self.stdout.write(self.style.WARNING(
                f"{user.username}: differs in {', '.join(off)} (mail since {stored['updated']} is not in the "
                "stored totals; run with --rebuild if it persists)."))
        else:
            self.stdout.write(self.style.SUCCESS(f"{user.username}: stored totals match."))
