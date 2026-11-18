import pytest

from mail import actions
from mail.models import Folder, FolderRole, Message, OutboxOp, Thread
from mail.testing import corpus

C = corpus.by_name()
pytestmark = pytest.mark.django_db


def folder(role):
    return Folder.objects.get(role=role)


def test_initial_sync_ingests_everything(loaded):
    expected = len(corpus.build())
    assert Message.objects.count() == expected
    roles = set(Folder.objects.values_list("role", flat=True))
    assert {"inbox", "sent", "drafts", "junk", "trash", "archive"} <= roles


def test_huge_shuffled_thread_ends_up_as_one_thread(loaded):
    msgs = Message.objects.filter(message_id__startswith="huge")
    assert msgs.count() == 200
    assert msgs.values("thread_id").distinct().count() == 1
    t = msgs.first().thread
    assert t.message_count == 200
    assert t.subject == "[list] The never-ending thread"


def test_reply_threading_with_child_first(loaded):
    keys = ["trip0@manifest.test", "trip1@friends.test", "trip2@friends.test"]
    threads = set(Message.objects.filter(message_id__in=keys).values_list("thread_id", flat=True))
    assert len(threads) == 1
    t = Thread.objects.get(pk=threads.pop())
    assert t.message_count == 3


def test_subject_fallback_threading(loaded):
    a = Message.objects.get(message_id="m0@sender.test")  # "Lunch on Friday?"
    b = Message.objects.get(message_id="m25@sender.test")  # "Re: Lunch on Friday?" no refs
    assert a.thread_id == b.thread_id


def test_duplicate_message_ids(loaded):
    dups = Message.objects.filter(message_id="duplicate@work.test")
    assert dups.count() == 2
    assert dups[0].blob_id != dups[1].blob_id  # different content kept separately
    same = Message.objects.filter(subject="Filed copy")
    assert same.count() == 2
    assert same[0].blob_id == same[1].blob_id
    assert same[0].thread_id == same[1].thread_id
    assert same[0].thread.message_count == 1  # collapsed in the thread


def test_missing_message_id_gets_synthetic_key(loaded):
    m = Message.objects.get(subject="No headers to speak of")
    assert m.message_key.startswith("synthetic:")


def test_resync_is_idempotent(loaded, engine):
    before = Message.objects.count()
    engine.sync_all()
    assert Message.objects.count() == before


def test_new_mail_and_flag_changes_from_other_clients(loaded, engine, server):
    inbox = folder(FolderRole.INBOX)
    uid = server.deliver("INBOX", corpus.simple(500, "New <new@x.test>", "Fresh", "hello"))
    engine.sync_folder(inbox)
    m = Message.objects.get(server_folder=inbox, uid=uid)
    assert not m.seen
    server.select("INBOX")
    server.store_flags([uid], ["\\Seen", "\\Flagged"], [])
    engine.sync_folder(inbox)
    m.refresh_from_db()
    assert m.seen and m.flagged
    assert m.thread.starred


def test_expunge_elsewhere_removes_locally(loaded, engine, server):
    inbox = folder(FolderRole.INBOX)
    uid = server.deliver("INBOX", corpus.simple(501, "Gone <gone@x.test>", "Soon gone", "bye"))
    engine.sync_folder(inbox)
    server.select("INBOX")
    server.store_flags([uid], ["\\Deleted"], [])
    server.expunge_uids([uid])
    engine.sync_folder(inbox)
    assert not Message.objects.filter(server_folder=inbox, uid=uid).exists()


def test_uidvalidity_change_reloads_folder(loaded, engine, server):
    archive = folder(FolderRole.ARCHIVE)
    count = Message.objects.filter(server_folder=archive).count()
    server.reset_uidvalidity("Archive")
    engine.sync_folder(archive)
    archive.refresh_from_db()
    assert archive.uidvalidity == server.boxes["Archive"].uidvalidity
    assert Message.objects.filter(server_folder=archive).count() == count


def test_flags_write_back(loaded, executor, server):
    m = Message.objects.filter(folder__role=FolderRole.INBOX, seen=False).first()
    actions.set_flags([m], add=["\\Seen"])
    assert OutboxOp.objects.filter(kind="flags", status="pending").exists()
    executor.run_pending()
    assert "\\Seen" in server.flags_of("INBOX", m.uid)


def test_pending_local_change_not_overwritten_by_sync(loaded, engine, server):
    inbox = folder(FolderRole.INBOX)
    m = Message.objects.filter(folder=inbox, seen=False).first()
    actions.set_flags([m], add=["\\Seen"])  # queued, not yet executed
    engine.sync_folder(inbox)
    m.refresh_from_db()
    assert m.seen  # sync must not revert the pending change


def test_move_with_copyuid(loaded, executor, engine, server):
    inbox, archive = folder(FolderRole.INBOX), folder(FolderRole.ARCHIVE)
    m = Message.objects.filter(folder=inbox).first()
    old_uid = m.uid
    actions.move_messages([m], archive)
    m.refresh_from_db()
    assert m.folder_id == archive.pk and m.server_folder_id == inbox.pk
    executor.run_pending()
    m.refresh_from_db()
    assert m.server_folder_id == archive.pk and m.uid is not None
    assert old_uid not in server.boxes["INBOX"].msgs
    assert m.uid in server.boxes["Archive"].msgs
    engine.sync_all()
    assert Message.objects.filter(pk=m.pk).exists()  # not duplicated or dropped
    assert Message.objects.filter(blob=m.blob, server_folder=archive).count() >= 1


def test_move_without_uidplus_reconciles_on_sync(db, engine):
    from mail.imap.fake import FakeMailServer
    from mail.outbox import Executor

    srv = FakeMailServer(capabilities=("IMAP4REV1", "MOVE"))
    eng = type(engine)(srv)
    srv.deliver("INBOX", corpus.simple(600, "X <x@x.test>", "No uidplus", "body"))
    eng.sync_all()
    m = Message.objects.get(subject="No uidplus")
    actions.move_messages([m], Folder.objects.get(role="archive"))
    Executor(srv).run_pending()
    m.refresh_from_db()
    assert m.uid is None and m.server_folder.role == "archive"
    eng.sync_folder(Folder.objects.get(role="archive"))
    m.refresh_from_db()
    assert m.uid is not None
    assert Message.objects.filter(subject="No uidplus").count() == 1


def test_flag_op_after_move_waits_for_uid(db, engine):
    from mail.imap.fake import FakeMailServer
    from mail.outbox import Executor

    srv = FakeMailServer(capabilities=("IMAP4REV1", "MOVE"))
    eng = type(engine)(srv)
    srv.deliver("INBOX", corpus.simple(601, "X <x@x.test>", "Chain", "body"))
    eng.sync_all()
    m = Message.objects.get(subject="Chain")
    actions.move_messages([m], Folder.objects.get(role="archive"))
    actions.set_flags([m], add=["\\Flagged"])
    ex = Executor(srv)
    ex.run_pending()
    assert OutboxOp.objects.filter(kind="flags", status="pending").exists()  # deferred
    eng.sync_folder(Folder.objects.get(role="archive"))
    OutboxOp.objects.update(not_before=None)
    ex.run_pending()
    m.refresh_from_db()
    assert "\\Flagged" in srv.flags_of("Archive", m.uid)


def test_delete_forever_only_from_trash_and_uses_uid_expunge(loaded, executor, server):
    inbox = folder(FolderRole.INBOX)
    m = Message.objects.filter(folder=inbox).first()
    with pytest.raises(actions.ActionError):
        actions.delete_forever([m])
    trash = folder(FolderRole.TRASH)
    actions.move_messages([m], trash)
    executor.run_pending()
    m.refresh_from_db()
    actions.delete_forever([m])
    executor.run_pending()
    assert m.uid not in server.boxes["Trash"].msgs
    assert ("expunge", "Trash", (m.uid,)) in server.log


def test_expunge_refused_without_uidplus(db, engine):
    from mail.imap.fake import FakeMailServer
    from mail.outbox import Executor

    srv = FakeMailServer(capabilities=("IMAP4REV1", "MOVE"))
    eng = type(engine)(srv)
    uid = srv.deliver("Trash", corpus.simple(602, "X <x@x.test>", "Trash me", "body"))
    eng.sync_all()
    m = Message.objects.get(subject="Trash me")
    actions.delete_forever([m])
    Executor(srv).run_pending()
    assert uid in srv.boxes["Trash"].msgs  # nothing was expunged
    op = OutboxOp.objects.get(kind="expunge")
    assert "UIDPLUS" in op.last_error


def test_failed_move_is_reverted(loaded, executor, server):
    inbox = folder(FolderRole.INBOX)
    m = Message.objects.filter(folder=inbox).first()
    ghost = Folder.objects.create(name="Ghost", needs_create=False)
    actions.move_messages([m], ghost)
    for _ in range(10):
        OutboxOp.objects.update(not_before=None)
        executor.run_pending()
    m.refresh_from_db()
    assert m.folder_id == inbox.pk  # shown where it really is again
    assert OutboxOp.objects.get(kind="move").status == "failed"


def test_archive_creates_missing_folder(db, engine):
    from mail.imap.fake import FakeMailServer
    from mail.outbox import Executor

    srv = FakeMailServer(folders=("INBOX",))
    eng = type(engine)(srv)
    srv.deliver("INBOX", corpus.simple(603, "X <x@x.test>", "Archive me", "body"))
    eng.sync_all()
    m = Message.objects.get(subject="Archive me")
    actions.archive(m.thread, Folder.objects.get(role="inbox"))
    Executor(srv).run_pending()
    assert "Archive" in srv.boxes
    assert len(srv.boxes["Archive"].msgs) == 1


def test_deleted_flagged_mail_is_never_downloaded(db, engine, server):
    server.deliver("INBOX", corpus.simple(800, "X <x@x.test>", "Kept", "a"))
    server.deliver("INBOX", corpus.simple(801, "X <x@x.test>", "Doomed", "b"), flags=["\\Deleted"])
    engine.sync_all()
    assert Message.objects.filter(subject="Kept").exists()
    assert not Message.objects.filter(subject="Doomed").exists()
    before = server.full_fetches
    engine.sync_folder(Folder.objects.get(role=FolderRole.INBOX))
    assert server.full_fetches == before  # nothing re-downloaded


def test_poison_message_is_not_refetched_forever(db, engine, server, monkeypatch):
    from mail import sync as sync_mod

    server.deliver("INBOX", corpus.simple(802, "X <x@x.test>", "Poison", "boom"))
    calls = []

    def broken(*a, **k):
        calls.append(1)
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(sync_mod, "ingest_raw", broken)
    inbox_sync = lambda: engine.sync_folder(Folder.objects.get(role=FolderRole.INBOX))  # noqa: E731
    engine.sync_all()
    for _ in range(5):
        inbox_sync()
    assert len(calls) == sync_mod.MAX_INGEST_FAILURES


def test_uidvalidity_recorded_before_first_sync_finishes(db, engine, server, monkeypatch):
    server.deliver("INBOX", corpus.simple(803, "X <x@x.test>", "First", "a"))
    engine.sync_folder_list()
    inbox = Folder.objects.get(role=FolderRole.INBOX)

    def die(*a, **k):
        raise OSError("connection dropped")

    monkeypatch.setattr(server, "fetch_full", die)
    with pytest.raises(OSError):
        engine.sync_folder(inbox)
    inbox.refresh_from_db()
    assert inbox.uidvalidity == server.boxes["INBOX"].uidvalidity


def test_failed_op_listed_and_retried(loaded, executor, server, api):
    inbox = folder(FolderRole.INBOX)
    m = Message.objects.filter(folder=inbox).first()
    ghost = Folder.objects.create(name="Later", needs_create=False)
    actions.move_messages([m], ghost)
    for _ in range(10):
        OutboxOp.objects.update(not_before=None)
        executor.run_pending()
    failed = api.get("/api/ops/failed").json()
    assert len(failed) == 1 and failed[0]["description"].startswith("Move 1 message to Later")
    # The folder now exists on the server; retrying succeeds.
    server.create_folder("Later")
    assert api.post(f"/api/ops/{failed[0]['id']}", {"action": "retry"}).status_code == 200
    m.refresh_from_db()
    assert m.folder_id == ghost.pk  # shown where it's going again
    executor.run_pending()
    m.refresh_from_db()
    assert m.server_folder_id == ghost.pk and m.uid in server.boxes["Later"].msgs
    assert api.get("/api/ops/failed").json() == []


def test_failed_op_dismiss(loaded, executor, api):
    m = Message.objects.filter(folder__role=FolderRole.INBOX).first()
    actions.move_messages([m], Folder.objects.create(name="Nowhere", needs_create=False))
    for _ in range(10):
        OutboxOp.objects.update(not_before=None)
        executor.run_pending()
    op = api.get("/api/ops/failed").json()[0]
    api.post(f"/api/ops/{op['id']}", {"action": "dismiss"})
    assert api.get("/api/ops/failed").json() == []
