"""Mail ⇄ Kern tasks.

* "Make a task" on a conversation creates a Kern task that links back to the
  email (``Task.source = {"kind": "mail", "key": <Message-ID>, ...}``). The
  link is by Message-ID, so it survives resyncs; /api/mail/open finds the
  conversation again.
* A follow-up nudge ("remind me if nobody replies") is also a task, due on
  the nudge day, so it shows up in Today and Upcoming. The two stay in step:
  a reply in the conversation completes the task; completing or deleting the
  task closes the nudge; moving the task's date moves the nudge.
"""
from __future__ import annotations

import datetime as dt

from django.db.models import Max
from django.utils import timezone

FOLLOWUP = "mail_followup"
MAIL = "mail"
_syncing = {"on": False}  # guard: our own task writes must not echo back


def _local_date(d: dt.datetime) -> dt.date:
    return timezone.localtime(d).date()


def _new_task(**kw):
    from notes import tasks as ntasks
    from notes.models import Task

    top = Task.objects.aggregate(m=Max("position"))["m"] or 0
    t = Task(position=top + 1, **kw)
    t.save()
    ntasks.index_task(t)
    return t


def _who(recipients: list) -> str:
    if not recipients:
        return ""
    r = recipients[0]
    name = (r.get("name") or r.get("addr") or "").strip() if isinstance(r, dict) else str(r)
    return name + (f" and {len(recipients) - 1} more" if len(recipients) > 1 else "")


def task_for_thread(thread, *, title: str = "", due: dt.date | None = None, priority: int = 0):
    """A task from a conversation (the newest message is the one linked)."""
    from .models import Message

    last = Message.objects.filter(thread=thread).order_by("-sort_date").first()
    who = (last.from_name or last.from_addr) if last else ""
    desc = f"From {who}: {thread.subject}" if who else thread.subject
    if last and last.snippet:
        desc += "\n\n" + last.snippet[:300]
    return _new_task(
        title=(title or thread.subject or "Email")[:500], description=desc[:20000], due=due, priority=priority,
        source={"kind": MAIL, "key": last.message_key if last else "", "subject": thread.subject[:300],
                "from": (last.from_addr if last else "")},
    )


def task_for_followup(f) -> None:
    """Called when a follow-up is created."""
    who = _who(f.recipients)
    title = f"Follow up with {who}: {f.subject}" if who else f"Follow up: {f.subject}"
    _syncing["on"] = True
    try:
        t = _new_task(title=title[:500], due=_local_date(f.due_at),
                      description="If nobody replies by then, Kern reminds you. A reply completes this task.",
                      source={"kind": FOLLOWUP, "key": f.message_key, "subject": f.subject[:300],
                              "followup": f.pk})
    finally:
        _syncing["on"] = False
    type(f).objects.filter(pk=f.pk).update(task_id=str(t.id))
    f.task_id = str(t.id)


def followup_closed(f, *, replied: bool) -> None:
    """The nudge ended: a reply came (complete the task) or the user cancelled
    it in mail (remove the task)."""
    from notes import tasks as ntasks
    from notes.models import Task

    if not f.task_id:
        return
    t = Task.objects.filter(id=f.task_id).first()
    if t is None:
        return
    _syncing["on"] = True
    try:
        if replied:
            if not t.done:
                ntasks.set_done(t, True)
        else:
            from notes import search

            search.remove("task", [t.id])
            t.delete()
    finally:
        _syncing["on"] = False


def followup_moved(f) -> None:
    from notes.models import Task

    if f.task_id:
        _syncing["on"] = True
        try:
            Task.objects.filter(id=f.task_id).update(due=_local_date(f.due_at), done=False, completed_at=None)
        finally:
            _syncing["on"] = False


# --- task side (signals, connected in mail/apps.py) -----------------------------

def on_task_saved(sender, instance, **kw) -> None:
    if _syncing["on"]:
        return
    src = instance.source or {}
    if src.get("kind") != FOLLOWUP or not src.get("followup"):
        return
    from . import followups
    from .models import FollowUp, FollowUpStatus

    f = FollowUp.objects.filter(pk=src["followup"]).first()
    if f is None:
        return
    if instance.done and f.status in followups.OPEN:
        FollowUp.objects.filter(pk=f.pk).update(status=FollowUpStatus.DONE)
    elif not instance.done and instance.due and f.status in followups.OPEN and _local_date(f.due_at) != instance.due:
        at = timezone.make_aware(dt.datetime.combine(instance.due, dt.time(9, 0)))
        FollowUp.objects.filter(pk=f.pk).update(due_at=at, status=FollowUpStatus.WAITING)


def on_task_deleted(sender, instance, **kw) -> None:
    if _syncing["on"]:
        return
    src = instance.source or {}
    if src.get("kind") == FOLLOWUP and src.get("followup"):
        from . import followups
        from .models import FollowUp, FollowUpStatus

        FollowUp.objects.filter(pk=src["followup"], status__in=followups.OPEN).update(status=FollowUpStatus.CANCELLED)
