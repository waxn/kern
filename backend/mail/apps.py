from django.apps import AppConfig


class MailConfig(AppConfig):
    name = "mail"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from notes.models import Task

        from . import taskbridge

        post_save.connect(taskbridge.on_task_saved, sender=Task, dispatch_uid="mail-task-saved")
        post_delete.connect(taskbridge.on_task_deleted, sender=Task, dispatch_uid="mail-task-deleted")
