import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kern.settings")
application = get_wsgi_application()

# Watched bookmarks are checked for changes in the background (see notes/monitor.py).
from notes import monitor  # noqa: E402

monitor.start()
