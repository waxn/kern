from django.apps import AppConfig


class NotesConfig(AppConfig):
    name = "notes"

    def ready(self):
        from . import models_ci  # noqa: F401  (registers the CI tables with this app)
