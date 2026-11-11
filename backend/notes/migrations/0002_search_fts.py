from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("notes", "0001_initial")]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE VIRTUAL TABLE search_fts USING fts5("
                "title, body, tokenize='unicode61 remove_diacritics 2', prefix='2 3')"
            ),
            reverse_sql="DROP TABLE search_fts",
        )
    ]
