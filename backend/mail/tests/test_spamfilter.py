"""The built-in spam filter (mail/spamfilter.py): works with no private model."""
import pytest

from mail.models import Folder, FolderRole, Message
from mail.testing import corpus

pytestmark = pytest.mark.django_db


def inbox():
    return Folder.objects.get(role=FolderRole.INBOX)


def junk():
    return Folder.objects.get(role=FolderRole.JUNK)


def mail(n, sender="offers@stranger.test", extra=(), auth="pass", subject="Hello"):
    return corpus.msg([("From", f"Someone <{sender}>"), ("To", corpus.ME), ("Subject", subject),
                       ("Message-ID", f"<sf{n}@stranger.test>"), ("Date", "Mon, 16 Nov 2026 10:00:00 +0000"), *extra],
                      "Some text", auth=auth)


def where(n):
    return Message.objects.get(message_id=f"sf{n}@stranger.test").folder.role


def test_providers_spam_verdict_moves_new_mail_to_junk(loaded, engine, server):
    server.deliver("INBOX", mail(1, extra=[("X-Spam-Flag", "YES")]))
    server.deliver("INBOX", mail(2, extra=[("X-Spam-Status", "No, score=0.1")]))
    server.deliver("INBOX", mail(3, extra=[("X-Rspamd-Action", "reject")]))
    engine.sync_folder(inbox())
    assert (where(1), where(2), where(3)) == (FolderRole.JUNK, FolderRole.INBOX, FolderRole.JUNK)
    m = Message.objects.get(message_id="sf1@stranger.test")
    assert any(f["rule"] == "spam-filter" and f["by"] == "provider" for f in m.risk_findings)
    assert m.risk_score == Message.objects.get(pk=m.pk).risk_score


def test_failed_authentication_from_a_stranger_is_junked(loaded, engine, server):
    server.deliver("INBOX", mail(4, auth="fail"))
    engine.sync_folder(inbox())
    assert where(4) == FolderRole.JUNK


def test_people_you_wrote_to_are_never_junked(loaded, engine, server):
    server.deliver("INBOX", mail(5, sender="alice@friends.test", extra=[("X-Spam-Flag", "YES")], auth="fail"))
    engine.sync_folder(inbox())
    assert where(5) == FolderRole.INBOX


def test_a_conversation_you_took_part_in_is_never_junked(loaded, engine, server):
    own = Message.objects.filter(from_addr=corpus.ME).first()
    assert own is not None
    server.deliver("INBOX", mail(6, sender="stranger@elsewhere.test", extra=[
        ("X-Spam-Flag", "YES"), ("In-Reply-To", f"<{own.message_id}>"), ("References", f"<{own.message_id}>")]))
    engine.sync_folder(inbox())
    assert where(6) == FolderRole.INBOX


def test_learns_from_what_you_junk_and_forgets_when_you_rescue(loaded, engine, server):
    for n in (10, 11):
        server.deliver("Junk", mail(n, sender="deals@shop.example"))
    engine.sync_folder(junk())
    server.deliver("INBOX", mail(12, sender="deals@shop.example"))
    engine.sync_folder(inbox())
    assert where(12) == FolderRole.JUNK

    # One of their messages is rescued ("Not spam"): no more automatic junking.
    Message.objects.filter(message_id="sf10@stranger.test").update(keywords=["$NotJunk"])
    server.deliver("INBOX", mail(13, sender="deals@shop.example"))
    engine.sync_folder(inbox())
    assert where(13) == FolderRole.INBOX


def test_one_junked_message_is_not_enough_and_kept_mail_protects(loaded, engine, server):
    server.deliver("Junk", mail(20, sender="news@once.example"))
    engine.sync_folder(junk())
    server.deliver("INBOX", mail(21, sender="news@once.example"))
    engine.sync_folder(inbox())
    assert where(21) == FolderRole.INBOX

    server.deliver("INBOX", mail(24, sender="shop@mixed.example"), ["\\Seen"])  # you read one of theirs
    engine.sync_folder(inbox())
    for n in (22, 23):
        server.deliver("Junk", mail(n, sender="shop@mixed.example"))
    engine.sync_folder(junk())
    server.deliver("INBOX", mail(25, sender="shop@mixed.example"))
    engine.sync_folder(inbox())
    assert where(25) == FolderRole.INBOX


def test_shared_providers_are_never_junked_by_domain(loaded, engine, server):
    for n in (30, 31, 32, 33, 34):
        server.deliver("Junk", mail(n, sender=f"spam{n}@gmail.com"))
    engine.sync_folder(junk())
    server.deliver("INBOX", mail(35, sender="friend@gmail.com"))
    engine.sync_folder(inbox())
    assert where(35) == FolderRole.INBOX


def test_first_sync_backlog_is_left_alone(db, server, engine):
    server.deliver("INBOX", mail(40, extra=[("X-Spam-Flag", "YES")]))
    engine.sync_all()
    assert where(40) == FolderRole.INBOX


def test_sweep_dry_run_moves_nothing_and_apply_does(loaded, user, engine, server, capsys):
    from django.core.management import call_command

    server.deliver("INBOX", mail(50, extra=[("X-Spam-Flag", "YES")]))
    engine.sync_folder(inbox())
    Message.objects.filter(message_id="sf50@stranger.test").update(folder=inbox())  # as if it had slipped through
    call_command("spam_sweep", days=3650)
    assert where(50) == FolderRole.INBOX and "would go to Junk" in capsys.readouterr().out
    call_command("spam_sweep", days=3650, apply=True)
    assert where(50) == FolderRole.JUNK
