"""Stored mail stats (mail/stats.py): the backfill, the nightly incremental run, settling of
recent days, rebuilds, and that the page's numbers equal the on-demand count (stats.live)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from mail import actions, stats
from mail.models import Folder, FolderRole, Message, StatsDay, StatsReply, StatsSeen, StatsState
from mail.testing import corpus

TZ = ZoneInfo("Europe/Stockholm")
NOW = datetime(2026, 11, 20, 10, 0, tzinfo=TZ)  # a Friday, mid-morning
WINDOWS = (7, 30, 90, 365)


@pytest.fixture(autouse=True)
def _tz(settings):
    settings.TIME_ZONE = "Europe/Stockholm"  # day buckets must follow local midnight, not UTC


@pytest.fixture
def mailbox(db, server, engine, monkeypatch):
    """The messy corpus, dated over the week before NOW, delivered and synced."""
    monkeypatch.setattr(corpus, "BASE", NOW - timedelta(hours=166))
    for item in corpus.build():
        server.deliver(item.folder, item.raw, item.flags, item.date)
    engine.sync_all()
    return server


def stored(days):
    s = stats.compute(days)
    assert s["ready"]
    return s


def assert_same(days, now):
    """The stored totals give the page exactly what counting the messages again gives."""
    s, live = stored(days), stats.live(days, now=now)
    for k in ("days", "received", "sent", "readRate", "newsletterShare", "withFiles", "perDay",
              "replyMedianMinutes", "replies", "series", "hours", "weekdays", "topDomains", "peakHour",
              "busiestDay"):
        assert s[k] == live[k], k
    strip = lambda rows: [{k: r[k] for k in ("addr", "name", "count", "unread", "label")} for r in rows]
    assert strip(s["topSenders"]) == strip(live["topSenders"])
    for k, v in live["totals"].items():
        assert s["totals"][k] == v, k


def new_mail(server, engine, n, when, folder="INBOX", sender="news@fresh.test", seen=False):
    for i in range(n):
        raw = (f"From: Fresh <{sender}>\r\nTo: {corpus.ME}\r\nSubject: new {i}\r\n"
               f"Message-ID: <new-{when.timestamp()}-{i}@fresh.test>\r\n"
               f"Date: {when.strftime('%a, %d %b %Y %H:%M:%S %z')}\r\n\r\nhello\r\n").encode()
        server.deliver(folder, raw, ["\\Seen"] if seen else [], when)
    engine.sync_all()


def test_not_ready_until_first_run(mailbox, api):
    assert api.get("/api/mail/stats", days=30).json() == {"ready": False, "days": 30}
    assert stats.due(NOW)


def test_backfill_in_batches_matches_live(mailbox, monkeypatch):
    monkeypatch.setattr(stats, "BATCH", 3)
    total = Message.objects.exclude(folder__role__in=stats.HIDDEN).count()
    assert total > 9
    # A tiny budget stops after every batch: the backfill resumes where it left off.
    steps = 0
    while not stats.run(NOW, budget=0):
        steps += 1
        state = StatsState.objects.get()
        assert state.run_top is not None and 0 < state.last_pk <= state.run_top
        assert stats.compute(30) == {"ready": False, "days": 30}  # no half-done numbers on the page
    assert steps >= total // 3 - 1
    state = StatsState.objects.get()
    assert state.run_top is None and state.updated == NOW
    assert state.last_pk == Message.objects.order_by("-pk").first().pk
    for days in WINDOWS:
        assert_same(days, NOW)
    s = stored(30)
    assert s["received"] > 0 and s["sent"] > 0
    assert sum(d["received"] for d in s["series"]) == s["received"] == sum(s["hours"]) == sum(s["weekdays"])
    assert s["series"][-1]["day"] == "2026-11-20"


def test_backfill_never_loads_more_than_a_batch(mailbox, monkeypatch):
    monkeypatch.setattr(stats, "BATCH", 4)
    sizes = []
    real = stats._add
    monkeypatch.setattr(stats, "_add", lambda rows, *a: (sizes.append(len(rows)), real(rows, *a)))
    stats.run(NOW)
    assert sizes and max(sizes) <= 4


def test_nightly_run_adds_only_new_mail(mailbox, server, engine, monkeypatch):
    new_mail(server, engine, 3, datetime(2026, 10, 2, 9, 0, tzinfo=TZ), sender="old@past.test", seen=True)
    stats.run(NOW)
    before = stored(30)
    mark = StatsState.objects.get().last_pk
    assert not stats.due(NOW + timedelta(hours=5))  # same day
    tonight = datetime(2026, 11, 21, 2, 30, tzinfo=TZ)
    assert not stats.due(tonight)  # not before NIGHT_HOUR
    new_mail(server, engine, 5, datetime(2026, 11, 20, 18, 15, tzinfo=TZ))
    assert stored(30)["received"] == before["received"]  # left out until the nightly run

    later = datetime(2026, 11, 21, 3, 5, tzinfo=TZ)
    assert stats.due(later)
    rows_seen = []
    real = stats._add
    monkeypatch.setattr(stats, "_add", lambda rows, *a: (rows_seen.extend(rows), real(rows, *a)))
    stats.run(later)
    # Only mail past the mark, plus the settle window (SETTLE_DAYS before the previous run).
    settle_from = datetime(2026, 11, 13, tzinfo=TZ)
    assert rows_seen and all(r[0] > mark or r[1] >= settle_from for r in rows_seen)
    assert any(r[0] > mark for r in rows_seen)
    old_outside = Message.objects.filter(pk__lte=mark, sort_date__lt=settle_from).exclude(
        folder__role__in=stats.HIDDEN)
    assert old_outside.exists() and not ({r[0] for r in rows_seen} & set(old_outside.values_list("pk", flat=True)))

    after = stored(30)
    assert after["received"] == before["received"] + 5
    friday = next(d for d in after["series"] if d["day"] == "2026-11-20")
    assert friday["received"] == next(d for d in before["series"] if d["day"] == "2026-11-20")["received"] + 5
    assert any(t["addr"] == "news@fresh.test" and t["count"] == 5 for t in after["topSenders"])
    assert after["hours"][18] == before["hours"][18] + 5
    for days in WINDOWS:
        assert_same(days, later)


def test_copies_and_moves_count_once(mailbox, server, engine):
    stats.run(NOW)
    before = stored(90)
    inbox = Folder.objects.get(role=FolderRole.INBOX)
    archive = actions.role_folder(FolderRole.ARCHIVE)
    m = Message.objects.filter(folder=inbox).order_by("pk").first()
    # A second copy of the same message (same Message-ID) shows up in another folder.
    server.deliver(archive.name, b"Message-ID: " + m.message_id.encode() + b"\r\nFrom: x@y.test\r\n\r\nx\r\n",
                   [], m.sort_date)
    engine.sync_all()
    assert Message.objects.filter(message_key=m.message_key).count() == 2
    nxt = datetime(2026, 11, 21, 4, 0, tzinfo=TZ)
    stats.run(nxt)
    assert stored(90)["received"] == before["received"]
    assert StatsSeen.objects.filter(key=m.message_key).count() == 1


def test_settling_picks_up_reads_and_trash(mailbox):
    stats.run(NOW)
    before = stored(30)
    inbox = Folder.objects.get(role=FolderRole.INBOX)
    unread = list(Message.objects.filter(folder=inbox, seen=False).exclude(from_addr__iexact=corpus.ME)
                  .order_by("pk")[:2])
    assert len(unread) == 2
    actions.set_flags([unread[0]], add=["\\Seen"])
    actions.move_messages([unread[1]], actions.role_folder(FolderRole.TRASH))
    nxt = datetime(2026, 11, 21, 4, 0, tzinfo=TZ)
    stats.run(nxt)
    after = stored(30)
    assert after["received"] == before["received"] - 1
    assert after["readRate"] != before["readRate"]
    for days in WINDOWS:
        assert_same(days, nxt)


def test_rebuild_fixes_drift_outside_the_settle_window(mailbox):
    stats.run(NOW)
    stats.run(NOW + timedelta(days=20))  # the corpus days are settled for good now
    much_later = NOW + timedelta(days=21)
    old = Message.objects.filter(folder__role=FolderRole.INBOX).exclude(from_addr__iexact=corpus.ME).order_by("pk").first()
    actions.move_messages([old], actions.role_folder(FolderRole.TRASH))
    stats.run(much_later)  # the old message's day is long settled: the nightly run keeps counting it
    assert stored(90)["received"] == stats.live(90, now=much_later)["received"] + 1
    stats.rebuild(much_later)
    for days in WINDOWS:
        assert_same(days, much_later)


def test_reply_counted_before_its_original_is_matched_later(mailbox, server, engine):
    stats.run(NOW)
    asked = datetime(2026, 11, 20, 12, 0, tzinfo=TZ)
    reply = (f"From: Me <{corpus.ME}>\r\nTo: q@ask.test\r\nSubject: Re: q\r\nMessage-ID: <r1@manifest.test>\r\n"
             f"In-Reply-To: <q1@ask.test>\r\nDate: {(asked + timedelta(minutes=90)).strftime('%a, %d %b %Y %H:%M:%S %z')}"
             "\r\n\r\nyes\r\n").encode()
    server.deliver("Sent", reply, ["\\Seen"], asked + timedelta(minutes=90))
    engine.sync_all()
    night = datetime(2026, 11, 21, 4, 0, tzinfo=TZ)
    stats.run(night)
    pending = StatsReply.objects.get(parent_key__contains="q1@ask.test")
    assert pending.seconds is None  # the question isn't here yet
    question = (f"From: Q <q@ask.test>\r\nTo: {corpus.ME}\r\nSubject: q\r\nMessage-ID: <q1@ask.test>\r\n"
                f"Date: {asked.strftime('%a, %d %b %Y %H:%M:%S %z')}\r\n\r\n?\r\n").encode()
    server.deliver("INBOX", question, [], asked)
    engine.sync_all()
    stats.run(night + timedelta(days=1))
    assert StatsReply.objects.get(parent_key__contains="q1@ask.test").seconds == 90 * 60
    assert_same(30, night + timedelta(days=1))


def test_page_reads_stored_totals_only(mailbox, api, django_assert_max_num_queries):
    stats.run(NOW)
    with django_assert_max_num_queries(12):
        s = api.get("/api/mail/stats", days=365).json()
    assert s["ready"] and s["updated"].startswith("2026-11-20")
    assert StatsDay.objects.count() <= 365


def test_worker_slice(mailbox, monkeypatch):
    from mail.worker import Worker

    monkeypatch.setattr(stats, "BATCH", 2)
    w = Worker(lambda: None, None, use_idle=False, require_config=False)
    busy = True
    while busy:
        busy = w.update_stats()
    assert StatsState.objects.get().updated is not None
    assert w.update_stats() is False  # nothing due until tomorrow night
