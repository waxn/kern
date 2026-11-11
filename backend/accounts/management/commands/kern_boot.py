import sys

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand

from accounts import site
from kern import tenancy


class Command(BaseCommand):
    help = "Prepare the databases (shared and every user's) and show the setup code on first run."

    def handle(self, *args, **options):
        call_command("migrate", database="default", interactive=False, verbosity=0)
        for uid in User.objects.values_list("id", flat=True):
            tenancy.ensure_db(uid)
        if site.setup_complete():
            return
        code = site.setup_code()
        legacy = (settings.DATA_DIR / "kern.sqlite3").exists()
        bar = "=" * 62
        lines = [
            "", bar, "  KERN IS NOT SET UP YET", "",
            "  Open the address of this server in a browser to finish setup.",
            f"  Setup code:  {code}", "",
        ]
        if legacy:
            lines += ["  Existing notes were found. The administrator you create",
                      "  first will take them over.", ""]
        lines += [bar, ""]
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
