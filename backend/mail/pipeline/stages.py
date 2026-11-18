"""Built-in pipeline stages. Order is set in settings.MAIL_PIPELINE."""

from __future__ import annotations

from django.db.models import F, Q
from django.utils import timezone

from .. import risk, spam
from ..models import Correspondent, FolderRole, Message
from ..risk import auth as auth_mod
from ..risk.domains import org_domain
from . import Context, Stage
from mail.account import cfg as _mail_cfg


class RiskStage(Stage):
    """Rule-based phishing score (mail/risk). Runs before ContactsStage so
    'first-time sender' sees history from before this message."""

    name = "risk"
    version = 1

    def applies(self, ctx: Context) -> bool:
        return not ctx.from_me and ctx.message.folder.role not in (FolderRole.SENT, FolderRole.DRAFTS)

    def run(self, ctx: Context) -> None:
        m, pm = ctx.message, ctx.parsed
        items = []
        if pm.msg is not None:
            try:
                items = list(pm.msg.items())
            except Exception:
                items = []
        auth = auth_mod.parse(auth_mod.trusted_headers(items, _authserv_id()))

        corr = Correspondent.objects.filter(address=m.from_addr).first()
        known = bool(corr and corr.received_count > 0 and corr.first_seen and corr.first_seen < m.sort_date)
        wrote = bool(corr and corr.sent_count > 0)

        names, domains = _contacts()

        x = risk.RiskInput(
            from_addr=m.from_addr,
            from_name=m.from_name,
            reply_to=[a["addr"] for a in m.reply_to],
            return_path=pm.return_path,
            auth=auth,
            links=pm.links(),
            attachment_names=[a.filename for a in pm.attachments],
            brands=risk.brands(),
            known_sender=known,
            you_wrote_to_sender=wrote,
            contact_names=names,
            contact_domains=domains,
        )
        score, level, findings = risk.evaluate(x, skip_history=ctx.initial)
        m.auth_results = auth
        m.risk_score, m.risk_level, m.risk_findings = score, level, findings
        m.save(update_fields=["auth_results", "risk_score", "risk_level", "risk_findings"])


# Per user (several users' workers share a process): {uid: {"key", "names", "domains"}}.
_contact_cache: dict = {}


def _contacts() -> tuple[dict[str, set[str]], set[str]]:
    """People you've written to: display names and their domains. Rebuilt
    only when the contact set changes (one cheap aggregate per message
    instead of loading up to 5000 rows)."""
    from django.db.models import Count, Max

    qs = Correspondent.objects.filter(sent_count__gt=0)
    agg = qs.aggregate(n=Count("id"), last=Max("id"), seen=Max("last_seen"), sent=Max("sent_count"))
    key = (agg["n"], agg["last"], agg["seen"], agg["sent"])
    from kern import tenancy

    entry = _contact_cache.setdefault(tenancy.current_uid() if not tenancy.testing() else "test",
                                      {"key": None, "names": {}, "domains": set()})
    if key != entry["key"]:
        names: dict[str, set[str]] = {}
        domains: set[str] = set()
        for c in qs.only("address", "name")[:5000]:
            if c.name:
                names.setdefault(c.name.casefold().strip(), set()).add(c.address)
            dom = c.address.rpartition("@")[2]
            if dom and not spam.is_shared_provider(dom):
                domains.add(org_domain(dom))
        entry.update(key=key, names=names, domains=domains)
    return entry["names"], entry["domains"]


def _authserv_id() -> str:
    from django.conf import settings

    return _mail_cfg()["AUTHSERV_ID"]


class ContactsStage(Stage):
    """Keeps the Correspondent table (who you talk to) up to date."""

    name = "contacts"
    version = 1

    def run(self, ctx: Context) -> None:
        m = ctx.message
        # Count each Message-ID once, even if copies sit in several folders.
        if Message.objects.filter(message_key=m.message_key, pipeline__has_key=self.name).exclude(pk=m.pk).exists():
            return
        when = m.sort_date or timezone.now()
        if ctx.from_me:
            for a in (m.to_addrs or []) + (m.cc_addrs or []) + (m.bcc_addrs or []):
                if a.get("addr") and a["addr"] not in ctx.me:
                    _bump(a["addr"], a.get("name", ""), when, sent=True)
        elif m.from_addr:
            _bump(m.from_addr, m.from_name, when, sent=False)


def _bump(addr: str, name: str, when, *, sent: bool) -> None:
    corr, created = Correspondent.objects.get_or_create(
        address=addr[:512],
        defaults={"name": name[:512], "first_seen": when, "last_seen": when,
                  "sent_count": 1 if sent else 0, "received_count": 0 if sent else 1},
    )
    if created:
        return
    field = "sent_count" if sent else "received_count"
    updates = {field: F(field) + 1}
    if corr.first_seen is None or when < corr.first_seen:
        updates["first_seen"] = when
    if corr.last_seen is None or when > corr.last_seen:
        updates["last_seen"] = when
        if name:
            updates["name"] = name[:512]
    elif name and not corr.name:
        updates["name"] = name[:512]
    Correspondent.objects.filter(pk=corr.pk).update(**updates)


class BlockListStage(Stage):
    """Mail from a blocked address/domain arriving in the Inbox is moved to
    Junk (on the server too)."""

    name = "blocklist"
    version = 1

    def applies(self, ctx: Context) -> bool:
        return ctx.message.folder.role == FolderRole.INBOX and not ctx.from_me

    def run(self, ctx: Context) -> None:
        from .. import actions

        rule = spam.matching_rule(ctx.message.from_addr)
        if rule is None:
            return
        type(rule).objects.filter(pk=rule.pk).update(hits=F("hits") + 1)
        ctx.message.routed_by_block = rule
        ctx.message.save(update_fields=["routed_by_block"])
        actions.move_messages([ctx.message], actions.role_folder(FolderRole.JUNK))


class PackageStage(Stage):
    """Shipping emails -> Shipment rows (mail/packages.py). Rules only."""

    name = "packages"
    version = 1

    def applies(self, ctx: Context) -> bool:
        return not ctx.from_me and ctx.message.folder.role not in (
            FolderRole.SENT, FolderRole.DRAFTS, FolderRole.JUNK, FolderRole.TRASH)

    def run(self, ctx: Context) -> None:
        from .. import packages
        from ..models import Shipment
        from ..risk.domains import org_label

        m, pm = ctx.message, ctx.parsed
        found = packages.scan(m.subject, pm.text or "", m.from_addr, m.sort_date).packages
        sender_dom = m.from_addr.rpartition("@")[2]
        for f in found:
            s, created = Shipment.objects.get_or_create(
                carrier=f.carrier, number=f.number,
                defaults={"status": f.status, "status_at": m.sort_date, "expected": f.expected,
                          "expected_text": f.expected_text, "subject": m.subject[:500], "thread": m.thread,
                          "message_keys": [m.message_key]},
            )
            carrier = packages.CARRIERS.get(f.carrier)
            from_carrier = carrier and any(sender_dom == d or sender_dom.endswith("." + d) for d in carrier.domains)
            if not from_carrier and not s.merchant:
                s.merchant = (m.from_name or org_label(sender_dom).title())[:200]
            before = None if created else s.status
            if not created:
                if m.message_key not in s.message_keys:
                    s.message_keys = (s.message_keys + [m.message_key])[-50:]
                if s.status_at is None or m.sort_date >= s.status_at:
                    s.status, s.status_at = f.status, m.sort_date
                    if f.expected or f.status == "delivered":
                        s.expected, s.expected_text = f.expected, f.expected_text
                if not from_carrier or not s.thread_id:
                    s.thread = m.thread
            s.save()
            if not ctx.initial and s.status != before and not s.hidden:
                from .. import events

                events.emit("package", id=s.pk, status=s.status, thread=s.thread_id)


class MuteStage(Stage):
    """New mail in a muted conversation skips the Inbox: archived and read."""

    name = "mute"
    version = 1

    def applies(self, ctx: Context) -> bool:
        return ctx.message.folder.role == FolderRole.INBOX and not ctx.from_me

    def run(self, ctx: Context) -> None:
        from .. import actions, mute

        m = mute.mute_for_thread(ctx.message.thread_id)
        if m is None:
            return
        if ctx.message.message_key not in m.message_keys:
            m.message_keys = sorted(set(m.message_keys) | {ctx.message.message_key})
            m.save(update_fields=["message_keys"])
        if not ctx.message.seen:
            actions.set_flags([ctx.message], add=["\\Seen"])
        actions.move_messages([ctx.message], actions.role_folder(FolderRole.ARCHIVE))


class SnoozeReplyStage(Stage):
    """A new message brings a snoozed conversation back early and closes any
    "nudge me if no reply" on it."""

    name = "snooze-reply"
    version = 1

    def applies(self, ctx: Context) -> bool:
        return not ctx.initial and not ctx.from_me and ctx.message.folder.role not in (FolderRole.SENT, FolderRole.DRAFTS)

    def run(self, ctx: Context) -> None:
        from .. import followups, snooze

        followups.on_new_message(ctx.message)
        if ctx.message.folder.role == FolderRole.INBOX:
            snooze.wake_for_new_message(ctx.message)


__all__ = ["RiskStage", "ContactsStage", "BlockListStage", "SnoozeReplyStage", "Q"]
