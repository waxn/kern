"""Mail stats: how much arrives, from whom, when, how fast you answer.

Everything is computed from the local copy in one pass over the last ``days`` days (and a few
cheap totals), so it's quick even for big mailboxes and nothing leaves the server.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from statistics import median

from django.db.models import Count, Sum
from django.utils import timezone

from .identity import my_addresses
from .models import Attachment, Folder, FolderRole, Message, Thread
from .names import display_name

HIDDEN = (FolderRole.TRASH, FolderRole.JUNK)


def compute(days: int = 90) -> dict:
    days = max(7, min(365, days))
    now = timezone.now()
    tz = timezone.get_current_timezone()
    since = now - timedelta(days=days)
    me = my_addresses()

    rows = list(
        Message.objects.filter(sort_date__gte=since).exclude(folder__role__in=HIDDEN)
        .values_list("id", "sort_date", "from_addr", "from_name", "seen", "folder__role", "size", "message_id",
                     "in_reply_to", "thread_id", "headers__list-unsubscribe", "has_attachments")
    )
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
    for mid, when, addr, name, seen, role, size, msgid, reply_to, tid, unsub, files in rows:
        key = msgid or f"#{mid}"
        if key in seen_ids:  # the same message in two folders counts once
            continue
        seen_ids.add(key)
        local = when.astimezone(tz)
        day = local.date().isoformat()
        mine = (addr or "").lower() in me or role == FolderRole.SENT
        if mine:
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
        if msgid:
            by_msgid[msgid] = when
        a = (addr or "").lower()
        if a:
            s = senders.setdefault(a, {"addr": a, "name": "", "count": 0, "unread": 0})
            s["count"] += 1
            s["unread"] += 0 if seen else 1
            if name and not s["name"]:
                s["name"] = name
            domains[a.rpartition("@")[2]] += 1

    waits = []
    for parent, when in my_replies:
        got = by_msgid.get(parent)
        if got and when > got:
            waits.append((when - got).total_seconds())

    series = []
    for i in range(days - 1, -1, -1):
        d = (now.astimezone(tz) - timedelta(days=i)).date().isoformat()
        series.append({"day": d, "received": received_by_day.get(d, 0), "sent": sent_by_day.get(d, 0)})

    top = sorted(senders.values(), key=lambda s: (-s["count"], s["addr"]))[:12]
    for s in top:
        s["label"] = display_name({"name": s["name"], "addr": s["addr"]})

    inbox = Folder.objects.filter(role=FolderRole.INBOX).first()
    totals = Message.objects.exclude(folder__role__in=HIDDEN).aggregate(n=Count("id"), size=Sum("size"))
    files = Attachment.objects.filter(inline=False).aggregate(n=Count("id"), size=Sum("size"))
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
        "topDomains": [{"domain": d, "count": n} for d, n in domains.most_common(8)],
        "totals": {
            "messages": totals["n"] or 0,
            "bytes": totals["size"] or 0,
            "threads": Thread.objects.count(),
            "attachments": files["n"] or 0,
            "attachmentBytes": files["size"] or 0,
            "inboxUnread": Message.objects.filter(folder=inbox, seen=False).values("thread_id").distinct().count() if inbox else 0,
            "inbox": Message.objects.filter(folder=inbox).values("thread_id").distinct().count() if inbox else 0,
        },
        "peakHour": max(range(24), key=lambda h: hours[h]) if received else None,
        "busiestDay": max(range(7), key=lambda d: weekdays[d]) if received else None,
    }

