"""Full-text search over mail with SQLite FTS5 (like notes/search.py).

An external-content FTS5 table indexes subject, sender, recipients,
attachment names and body text of mail_message; triggers keep it in step.
Diacritics are folded (resume finds résumé).
"""
from django.db import migrations

COLS = "subject, from_name, from_addr, search_recipients, attachment_names, body_text"
NEW = "new.subject, new.from_name, new.from_addr, new.search_recipients, new.attachment_names, new.body_text"
OLD = "old.subject, old.from_name, old.from_addr, old.search_recipients, old.attachment_names, old.body_text"

FORWARD = [
    f"""CREATE VIRTUAL TABLE mail_message_fts USING fts5(
        {COLS}, content='mail_message', content_rowid='id',
        tokenize='unicode61 remove_diacritics 2', prefix='2 3')""",
    f"""CREATE TRIGGER mail_message_fts_ai AFTER INSERT ON mail_message BEGIN
        INSERT INTO mail_message_fts(rowid, {COLS}) VALUES (new.id, {NEW}); END""",
    f"""CREATE TRIGGER mail_message_fts_ad AFTER DELETE ON mail_message BEGIN
        INSERT INTO mail_message_fts(mail_message_fts, rowid, {COLS}) VALUES ('delete', old.id, {OLD}); END""",
    f"""CREATE TRIGGER mail_message_fts_au AFTER UPDATE OF {COLS} ON mail_message BEGIN
        INSERT INTO mail_message_fts(mail_message_fts, rowid, {COLS}) VALUES ('delete', old.id, {OLD});
        INSERT INTO mail_message_fts(rowid, {COLS}) VALUES (new.id, {NEW}); END""",
    "INSERT INTO mail_message_fts(mail_message_fts) VALUES ('rebuild')",
]
BACKWARD = [
    "DROP TRIGGER IF EXISTS mail_message_fts_au",
    "DROP TRIGGER IF EXISTS mail_message_fts_ad",
    "DROP TRIGGER IF EXISTS mail_message_fts_ai",
    "DROP TABLE IF EXISTS mail_message_fts",
]


class Migration(migrations.Migration):
    dependencies = [("mail", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
