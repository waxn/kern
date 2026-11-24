"""Mail stats: how much arrives, from whom, when, how fast you answer.

The page reads stored running totals (StatsDay, StatsSender, StatsReply in models.py), so
opening it costs a handful of small queries however big the mailbox is. The totals are kept
by ``run()``, which the mail worker calls; it does real work once a night (after NIGHT_HOUR):

* New mail: every message past the high-water mark (StatsState.last_pk) is added into the
  buckets of its local day, in batches, each batch committed together with the new mark.
  The first run starts from mark 0, so it is the backfill, and an interrupted run resumes.
* Settling: the last SETTLE_DAYS days before the previous run are taken out and counted
  again from the messages as they are now. Recent mail is what changes: it gets read, moved
  to Trash or Junk, or archived. Older drift (an old message deleted years later) stays until
  ``python manage.py mail_stats --rebuild``.
* A ledger (StatsSeen) of counted message keys makes sure a copy in a second folder, or a
  message moved after it was counted, never counts twice.

Mail that arrived after the last run is left out until the next one. The page says when the
totals were made ("Updated ..."): adding today's mail on top would need the ledger checks and
reply matching at request time, which is what this design takes off the request path, and a
day's worth of mail barely moves a 30-day picture.

``live()`` is the old on-demand computation, kept as the reference the stored totals are
checked against (tests, and ``mail_stats --check``).
"""

from __future__ import annotations

import time as _time
from collections import Counter
from datetime import datetime, time, timedelta
from statistics import median

from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

from kern import tenancy

from .identity import my_addresses
from .models import (Attachment, Folder, FolderRole, Message, StatsDay, StatsReply, StatsSeen, StatsSender,
                     StatsState, Thread, ThreadFolder)
from .names import display_name

HIDDEN = (FolderRole.TRASH, FolderRole.JUNK)
NIGHT_HOUR = 3  # local hour after which the nightly run starts
SETTLE_DAYS = 7  # days before the previous run that are counted again
BATCH = 500
UNMATCHED_KEEP_DAYS = 30  # how long a reply waits for the message it answers to turn up
CHUNK = 500  # sqlite host parameters per IN (...)

FIELDS = ("id", "sort_date", "from_addr", "from_name", "seen", "folder__role", "message_key", "in_reply_to",
          "headers__list-unsubscribe", "has_attachments")


def _chunks(items, n=CHUNK):
    items = list(items)
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _state() -> StatsState:
    return StatsState.objects.get_or_create(pk=1)[0]


def _midnight(day, tz):
    return timezone.make_aware(datetime.combine(day, time.min), tz)


# --- Keeping the totals ---------------------------------------------------------------------


def due(now=None, state: StatsState | None = None) -> bool:
    state = state or _state()
    if state.run_top is not None or state.updated is None:
        return True
    now = now or timezone.now()
    local = timezone.localtime(now)
    return local.date() > timezone.localdate(state.updated) and local.hour >= NIGHT_HOUR


def run(now=None, budget: float | None = None, force: bool = False) -> bool:
    """Bring the totals up to date if a run is due (or ``force``). With a ``budget`` in seconds,
    stop after the batch that uses it up; the next call carries on. True when nothing is left."""
    now = now or timezone.now()
    state = _state()
    if not force and not due(now, state):
        return True
    started = _time.monotonic()
    tz = timezone.get_current_timezone()
    me = my_addresses()
    if state.run_top is None:  # a new run: fix its upper end, then settle the recent days
        with tenancy.atomic():
            state.run_top = Message.objects.aggregate(n=Max("pk"))["n"] or 0
            if state.updated is not None:
                _settle(state, tz, me)
            state.save()
    while True:
        rows = _rows(Message.objects.filter(pk__gt=state.last_pk, pk__lte=state.run_top))
        if not rows:
            break
        with tenancy.atomic():
            _add(rows, tz, me)
            state.last_pk = max(r[0] for r in rows)
            state.save(update_fields=["last_pk"])
        if budget is not None and _time.monotonic() - started > budget:
            return False
    with tenancy.atomic():
        _match_replies(timezone.localdate(now, tz))
        state.last_pk = state.run_top
        state.run_top = None
        state.updated = now
        state.totals = _mailbox_totals()
        state.save()
    return True


def rebuild(now=None) -> None:
    """Throw the totals away and count everything again (in batches, as the first run does)."""
    with tenancy.atomic():
        for model in (StatsDay, StatsSender, StatsReply, StatsSeen, StatsState):
            model.objects.all().delete()
    run(now, force=True)


def _rows(qs) -> list:
    return list(qs.exclude(folder__role__in=HIDDEN).order_by("pk").values_list(*FIELDS)[:BATCH])


def _settle(state: StatsState, tz, me) -> None:
    """Take the days from SETTLE_DAYS before the previous run out of the totals and count the
    messages already behind the mark on those days again, as they are now."""
    cutoff = timezone.localdate(state.updated, tz) - timedelta(days=SETTLE_DAYS)
    for model in (StatsDay, StatsSender, StatsReply, StatsSeen):
        model.objects.filter(day__gte=cutoff).delete()
    qs = Message.objects.filter(pk__lte=state.last_pk, sort_date__gte=_midnight(cutoff, tz))
    after = 0
    while rows := _rows(qs.filter(pk__gt=after)):
        _add(rows, tz, me)
        after = rows[-1][0]


def _add(rows, tz, me) -> None:
    """Count a batch of messages into the stored totals."""
    known = set()
    for keys in _chunks({r[6] or f"#{r[0]}" for r in rows}):
        known.update(StatsSeen.objects.filter(key__in=keys).values_list("key", flat=True))
    days: dict = {}
    senders: dict = {}
    seen_rows, replies = [], []
    for mid, when, addr, name, seen, role, key, reply_to, unsub, files in rows:
        key = key or f"#{mid}"
        if key in known:  # the same message in two folders counts once
            continue
        known.add(key)
        local = when.astimezone(tz)
        day = local.date()
        b = days.setdefault(day, {"received": 0, "sent": 0, "read": 0, "newsletters": 0, "with_files": 0,
                                  "hours": [0] * 24})
        a = (addr or "").lower()
        if a in me or role == FolderRole.SENT:
            seen_rows.append(StatsSeen(key=key, day=day))
            b["sent"] += 1
            if reply_to:
                replies.append(StatsReply(day=day, at=when, parent_key=reply_to))
            continue
        seen_rows.append(StatsSeen(key=key, day=day, received_at=when))
        b["received"] += 1
        b["hours"][local.hour] += 1
        b["read"] += 1 if seen else 0
        b["newsletters"] += 1 if unsub else 0
        b["with_files"] += 1 if files else 0
        if a:
            s = senders.setdefault((day, a), {"name": "", "count": 0, "unread": 0})
            s["count"] += 1
            s["unread"] += 0 if seen else 1
            if name and not s["name"]:
                s["name"] = name[:512]

    StatsSeen.objects.bulk_create(seen_rows)
    StatsReply.objects.bulk_create(replies)

    have = {d.day: d for d in StatsDay.objects.filter(day__in=list(days))}
    new, changed = [], []
    for day, b in days.items():
        d = have.get(day)
        if d is None:
            new.append(StatsDay(day=day, **b))
            continue
        for f in ("received", "sent", "read", "newsletters", "with_files"):
            setattr(d, f, getattr(d, f) + b[f])
        d.hours = [x + y for x, y in zip(d.hours or [0] * 24, b["hours"])]
        changed.append(d)
    StatsDay.objects.bulk_create(new)
    StatsDay.objects.bulk_update(changed, ["received", "sent", "read", "newsletters", "with_files", "hours"])

    have = {}
    for addrs in _chunks({a for _, a in senders}):
        for s in StatsSender.objects.filter(day__in=list({d for d, _ in senders}), addr__in=addrs):
            have[(s.day, s.addr)] = s
    new, changed = [], []
    for (day, a), v in senders.items():
        s = have.get((day, a))
        if s is None:
            new.append(StatsSender(day=day, addr=a[:512], domain=a.rpartition("@")[2][:512], **v))
            continue
        s.count += v["count"]
        s.unread += v["unread"]
        s.name = s.name or v["name"]
        changed.append(s)
    StatsSender.objects.bulk_create(new)
    StatsSender.objects.bulk_update(changed, ["count", "unread", "name"])


def _match_replies(today) -> None:
    """Fill in the wait of replies whose original has been counted by now."""
    pending = list(StatsReply.objects.filter(seconds__isnull=True).values_list("id", "at", "parent_key"))
    if not pending:
        return
    parents = {}
    for keys in _chunks({p for _, _, p in pending}):
        for k, day, got in StatsSeen.objects.filter(key__in=keys, received_at__isnull=False).values_list(
                "key", "day", "received_at"):
            parents[k] = (day, got)
    done, drop = [], []
    for rid, at, parent in pending:
        if parent not in parents:
            continue
        day, got = parents[parent]
        if at > got:
            done.append(StatsReply(id=rid, parent_day=day, seconds=(at - got).total_seconds()))
        else:
            drop.append(rid)
    StatsReply.objects.bulk_update(done, ["parent_day", "seconds"])
    for ids in _chunks(drop):
        StatsReply.objects.filter(id__in=ids).delete()
    StatsReply.objects.filter(seconds__isnull=True, day__lt=today - timedelta(days=UNMATCHED_KEEP_DAYS)).delete()


def _mailbox_totals() -> dict:
    totals = Message.objects.exclude(folder__role__in=HIDDEN).aggregate(n=Count("id"), size=Sum("size"))
    files = Attachment.objects.filter(inline=False).aggregate(n=Count("id"), size=Sum("size"))
    return {
        "messages": totals["n"] or 0,
        "bytes": totals["size"] or 0,
        "threads": Thread.objects.count(),
        "attachments": files["n"] or 0,
        "attachmentBytes": files["size"] or 0,
    }


# --- Reading them -----------------------------------------------------------------------------


def _clamp(days: int) -> int:
    return max(7, min(365, days))


def compute(days: int = 90) -> dict:
    """The page's numbers, from the stored totals: the ``days`` local days up to the last run."""
    days = _clamp(days)
    state = StatsState.objects.filter(pk=1).first()
    if state is None or state.updated is None:
        return {"ready": False, "days": days}
    tz = timezone.get_current_timezone()
    end = timezone.localdate(state.updated, tz)
    start = end - timedelta(days=days - 1)

    by_day = {d.day: d for d in StatsDay.objects.filter(day__gte=start, day__lte=end)}
    received = sent = read = newsletters = with_files = 0
    hours = [0] * 24
    weekdays = [0] * 7
    series = []
    for i in range(days):
        day = start + timedelta(days=i)
        d = by_day.get(day)
        series.append({"day": day.isoformat(), "received": d.received if d else 0, "sent": d.sent if d else 0})
        if not d:
            continue
        received += d.received
        sent += d.sent
        read += d.read
        newsletters += d.newsletters
        with_files += d.with_files
        hours = [x + y for x, y in zip(hours, d.hours or [0] * 24)]
        weekdays[day.weekday()] += d.received

    in_range = StatsSender.objects.filter(day__gte=start, day__lte=end)
    top = list(in_range.values("addr").annotate(count=Sum("count"), unread=Sum("unread"))
               .order_by("-count", "addr")[:12])
    names = {}
    for addr, name in (in_range.filter(addr__in=[s["addr"] for s in top]).exclude(name="")
                       .order_by("day", "id").values_list("addr", "name")):
        names.setdefault(addr, name)
    for s in top:
        s["name"] = names.get(s["addr"], "")
        s["label"] = display_name({"name": s["name"], "addr": s["addr"]})
    domains = (in_range.values("domain").annotate(n=Sum("count")).order_by("-n", "domain")[:8])

    waits = list(StatsReply.objects.filter(day__gte=start, day__lte=end, parent_day__gte=start,
                                           seconds__isnull=False).values_list("seconds", flat=True))

    inbox = Folder.objects.filter(role=FolderRole.INBOX).first()
    in_inbox = ThreadFolder.objects.filter(folder=inbox) if inbox else ThreadFolder.objects.none()
    return {
        "ready": True,
        "updated": state.updated.isoformat(),
        "days": days,
        "received": received,
        "sent": sent,
        "readRate": round(read / received, 3) if received else None,
        "newsletterShare": round(newsletters / received, 3) if received else None,
        "withFiles": with_files,
        "perDay": round(received / days, 1),
        "replyMedianMinutes": round(median(waits) / 60) if waits else None,
        "replies": len(waits),
        "series": series,
        "hours": hours,
        "weekdays": weekdays,
        "topSenders": top,
        "topDomains": [{"domain": d["domain"], "count": d["n"]} for d in domains],
        "totals": {
            **{"messages": 0, "bytes": 0, "threads": 0, "attachments": 0, "attachmentBytes": 0},
            **state.totals,
            "inboxUnread": in_inbox.filter(unread=True).count(),
            "inbox": in_inbox.count(),
        },
        "peakHour": max(range(24), key=lambda h: hours[h]) if received else None,
        "busiestDay": max(range(7), key=lambda d: weekdays[d]) if received else None,
    }


def live(days: int = 90, now=None) -> dict:
    """The old on-demand computation over the ``days`` local days up to ``now`` (one pass over
    the messages). Too slow for the page on a big mailbox; kept as the reference the stored
    totals must agree with."""
    days = _clamp(days)
    now = now or timezone.now()
    tz = timezone.get_current_timezone()
    end = timezone.localdate(now, tz)
    start = end - timedelta(days=days - 1)
    me = my_addresses()

    rows = (Message.objects.filter(sort_date__gte=_midnight(start, tz), sort_date__lt=_midnight(end + timedelta(days=1), tz))
            .exclude(folder__role__in=HIDDEN).order_by("pk").values_list(*FIELDS))
    seen_ids = set()
    received_by_day: Counter = Counter()
    sent_by_day: Counter = Counter()
    hours = [0] * 24
    weekdays = [0] * 7
    senders: dict[str, dict] = {}
    domains: Counter = Counter()
    received = sent = read = newsletters = with_files = 0
    by_msgid = {}
    my_replies = []
    for mid, when, addr, name, seen, role, key, reply_to, unsub, files in rows.iterator(chunk_size=2000):
        key = key or f"#{mid}"
        if key in seen_ids:
            continue
        seen_ids.add(key)
        local = when.astimezone(tz)
        day = local.date().isoformat()
        a = (addr or "").lower()
        if a in me or role == FolderRole.SENT:
            sent += 1
            sent_by_day[day] += 1
            if reply_to:
                my_replies.append((reply_to, when))
            continue
        received += 1
        received_by_day[day] += 1
        hours[local.hour] += 1
        weekdays[local.weekday()] += 1
        read += 1 if seen else 0
        newsletters += 1 if unsub else 0
        with_files += 1 if files else 0
        by_msgid[key] = when
        if a:
            s = senders.setdefault(a, {"addr": a, "count": 0, "unread": 0, "name": ""})
            s["count"] += 1
            s["unread"] += 0 if seen else 1
            if name and not s["name"]:
                s["name"] = name[:512]
            domains[a.rpartition("@")[2]] += 1

    waits = []
    for parent, when in my_replies:
        got = by_msgid.get(parent)
        if got and when > got:
            waits.append((when - got).total_seconds())

    series = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        series.append({"day": d, "received": received_by_day.get(d, 0), "sent": sent_by_day.get(d, 0)})
    top = sorted(senders.values(), key=lambda s: (-s["count"], s["addr"]))[:12]
    for s in top:
        s["label"] = display_name({"name": s["name"], "addr": s["addr"]})
    return {
        "days": days,
        "received": received,
        "sent": sent,
        "readRate": round(read / received, 3) if received else None,
        "newsletterShare": round(newsletters / received, 3) if received else None,
        "withFiles": with_files,
        "perDay": round(received / days, 1),
        "replyMedianMinutes": round(median(waits) / 60) if waits else None,
        "replies": len(waits),
        "series": series,
        "hours": hours,
        "weekdays": weekdays,
        "topSenders": top,
        "topDomains": [{"domain": d, "count": n} for d, n in sorted(domains.items(), key=lambda x: (-x[1], x[0]))[:8]],
        "totals": _mailbox_totals(),
        "peakHour": max(range(24), key=lambda h: hours[h]) if received else None,
        "busiestDay": max(range(7), key=lambda d: weekdays[d]) if received else None,
    }
