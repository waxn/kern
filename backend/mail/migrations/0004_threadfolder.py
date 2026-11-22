"""ThreadFolder: a per-folder index of conversations (see mail/models.py)."""

import django.db.models.deletion
from django.db import migrations, models


def backfill(apps, schema_editor):
    Message = apps.get_model("mail", "Message")
    Thread = apps.get_model("mail", "Thread")
    ThreadFolder = apps.get_model("mail", "ThreadFolder")
    db = schema_editor.connection.alias
    dates = dict(Thread.objects.using(db).values_list("id", "last_date"))
    rows: dict[tuple[int, int], bool] = {}
    for tid, fid, seen in (Message.objects.using(db).filter(thread__isnull=False)
                           .values_list("thread_id", "folder_id", "seen").iterator(chunk_size=5000)):
        key = (fid, tid)
        rows[key] = rows.get(key, False) or not seen
    batch = [ThreadFolder(folder_id=f, thread_id=t, last_date=dates.get(t), unread=u) for (f, t), u in rows.items()]
    ThreadFolder.objects.using(db).bulk_create(batch, batch_size=2000)


class Migration(migrations.Migration):
    dependencies = [("mail", "0003_followup_task_id")]

    operations = [
        migrations.CreateModel(
            name="ThreadFolder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("last_date", models.DateTimeField(null=True)),
                ("unread", models.BooleanField(default=False)),
                ("folder", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="thread_rows", to="mail.folder")),
                ("thread", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="in_folders", to="mail.thread")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["folder", "-last_date", "-thread"], name="threadfolder_list"),
                    models.Index(fields=["folder", "unread", "-last_date", "-thread"], name="threadfolder_unread"),
                    models.Index(fields=["thread"], name="threadfolder_thread"),
                ],
                "constraints": [models.UniqueConstraint(fields=("folder", "thread"), name="threadfolder_unique")],
            },
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
