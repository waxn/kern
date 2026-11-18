import pytest

from mail import actions, spam
from mail.models import BlockRule, Folder, FolderRole, Message
from mail.testing import corpus

pytestmark = pytest.mark.django_db


def test_shared_provider_domain_cannot_be_blocked(db):
    with pytest.raises(spam.BlockError):
        spam.add_block("domain", "gmail.com")
    with pytest.raises(spam.BlockError):
        spam.add_block("domain", "mail.yahoo.co.uk".replace("mail.", ""))
    assert spam.is_shared_provider("googlemail.com")
    spam.add_block("address", "someone@gmail.com")  # single address is fine
    rule = spam.add_block("domain", "spammy.example")
    assert rule.value == "spammy.example"


def test_report_spam_moves_flags_and_blocks(loaded, executor, server):
    m = Message.objects.get(subject="WIN BIG NOW!!!")
    inbox = Folder.objects.get(role=FolderRole.INBOX)
    res = actions.report_spam(m.thread, inbox, block="domain")
    assert res["blocked"] == {"kind": "domain", "value": "spammy.example"}
    m.refresh_from_db()
    assert m.folder.role == FolderRole.JUNK
    executor.run_pending()
    m.refresh_from_db()
    assert m.uid in server.boxes["Junk"].msgs
    assert "$Junk" in server.flags_of("Junk", m.uid)


def test_report_spam_refuses_shared_domain(loaded):
    inbox = Folder.objects.get(role=FolderRole.INBOX)
    m = Message.objects.get(subject="Quick favour")  # from ...@gmail.test (not a real provider)
    spam.add_block("address", "x@gmail.com")
    fake = Message.objects.get(subject="Lunch on Friday?")
    fake.from_addr = "someone@gmail.com"
    fake.save()
    with pytest.raises(spam.BlockError):
        actions.report_spam(fake.thread, inbox, block="domain")
    assert m.pk


def test_blocked_sender_routed_to_junk(loaded, engine, server, executor):
    spam.add_block("address", "pest@annoying.example")
    inbox = Folder.objects.get(role=FolderRole.INBOX)
    server.deliver("INBOX", corpus.simple(700, "Pest <pest@annoying.example>", "Again", "hi"))
    server.deliver("INBOX", corpus.simple(701, "Sub <x@deep.spammy.example>", "Sub", "hi"))
    spam.add_block("domain", "spammy.example")
    engine.sync_folder(inbox)
    a = Message.objects.get(subject="Again")
    b = Message.objects.get(subject="Sub")
    assert a.folder.role == FolderRole.JUNK and a.routed_by_block is not None
    assert b.folder.role == FolderRole.JUNK  # subdomain covered
    executor.run_pending()
    a.refresh_from_db()
    assert a.uid in server.boxes["Junk"].msgs
    assert BlockRule.objects.get(value="pest@annoying.example").hits == 1


def test_not_spam_moves_back_and_unblocks(loaded, executor):
    m = Message.objects.get(subject="WIN BIG NOW!!!")
    inbox = Folder.objects.get(role=FolderRole.INBOX)
    actions.report_spam(m.thread, inbox, block="address")
    executor.run_pending()
    assert BlockRule.objects.filter(value="deals@spammy.example").exists()
    res = actions.not_spam(m.thread, None)
    assert "address:deals@spammy.example" in res["unblocked"]
    m.refresh_from_db()
    assert m.folder.role == FolderRole.INBOX
    assert not BlockRule.objects.exists()


def test_cannot_report_own_mail(loaded):
    m = Message.objects.get(message_id="trip0@manifest.test")
    sent = Folder.objects.get(role=FolderRole.SENT)
    with pytest.raises(actions.ActionError):
        actions.report_spam(m.thread, sent)
