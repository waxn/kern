"""The built-in spam filter: a few strict rules that need no model and no network.

New Inbox mail is moved to Junk when one of these is true:

  provider   your mail provider's own spam filter flagged it (X-Spam-Flag, X-Spam, X-Spam-Status,
             X-Rspamd-Action). Every provider that filters adds one of these.
  phishing   the sender is new to you and the phishing score (mail/risk) is "high": failed
             SPF/DKIM/DMARC, look-alike domains, fake brands and the like.
  learned    you have sent this address (or domain) to Junk before and never kept anything from it.

A false positive costs more than a missed spam, so every rule is held back by the same guards: never
anyone you have written to, never a conversation you took part in, never a sender you have told Kern
is "not spam", and never anyone who has sent you mail you kept.

Which of these ran is recorded on the message (a weight-0 finding, so the risk score is untouched).
"""

from __future__ import annotations

import logging

from . import spam
from .models import Correspondent, FolderRole, Message

log = logging.getLogger("kern.mail.spamfilter")

RULE = "spam-filter"
LEARN_ADDRESS = 2  # messages from one address in Junk (and none kept) before it is junk for good
LEARN_DOMAIN = 4  # same for a whole domain (never for shared providers like gmail.com)


def provider_flag(headers: dict) -> str:
    """Why your provider's filter called this spam, or "". Headers are the lower-cased ones Kern keeps."""
    def has(name: str) -> str:
        return (headers.get(name) or "").strip().lower()

    if has("x-spam-flag").startswith("yes") or has("x-spam").startswith("yes") or has("x-spam-status").startswith("yes"):
        return "Your mail provider's spam filter marked it as spam."
    if has("x-rspamd-action") in ("reject", "add header", "rewrite subject"):
        return "Your mail provider's spam filter (Rspamd) marked it as spam."
    return ""


def _history(addr: str, exclude_pk: int | None) -> dict:
    """How this address has fared before: counts of mail you junked, and mail you kept."""
    out = {"junked": 0, "kept": 0, "rescued": 0}
    qs = Message.objects.filter(from_addr=addr).select_related("folder")
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    for m in qs.only("keywords", "folder__role", "seen", "flagged", "answered")[:300]:
        kws = m.keywords or []
        if "$NotJunk" in kws:
            out["rescued"] += 1
        elif m.folder.role == FolderRole.JUNK or "$Junk" in kws:
            out["junked"] += 1
        elif m.folder.role != FolderRole.TRASH and (m.seen or m.flagged or m.answered):
            out["kept"] += 1  # unread mail does not count: it may just be spam nobody has looked at
    return out


def protected(message, me: set[str]) -> str:
    """Why this message must never be junked automatically, or "" when it may be."""
    corr = Correspondent.objects.filter(address=message.from_addr).first()
    if corr and corr.sent_count > 0:
        return "you have written to this sender"
    if message.thread_id and Message.objects.filter(thread_id=message.thread_id, from_addr__in=me).exists():
        return "you took part in this conversation"
    return ""


def judge(message, headers: dict, me: set[str]) -> tuple[str, str] | None:
    """("provider" | "phishing" | "learned", reason) when this new Inbox message should go to Junk."""
    if not message.from_addr or message.from_addr in me:
        return None
    if protected(message, me):
        return None
    mine = _history(message.from_addr, message.pk)
    if mine["rescued"] or mine["kept"]:
        # You have kept or rescued mail from them. Only the provider's own verdict outweighs that,
        # and not if you told us this sender is fine.
        if mine["rescued"]:
            return None
        why = provider_flag(headers)
        return ("provider", why) if why else None
    why = provider_flag(headers)
    if why:
        return "provider", why
    if message.risk_level == "high":
        return "phishing", "It looks like phishing (see the warnings on the message), and you have no history with this sender."
    if mine["junked"] >= LEARN_ADDRESS:
        return "learned", f"You have sent {mine['junked']} earlier messages from this address to Junk and kept none."
    dom = spam.domain_of(message.from_addr)
    if dom and not spam.is_shared_provider(dom) and _domain_junked(dom, message.pk):
        return "learned", f"You have sent several earlier messages from {dom} to Junk and kept none."
    return None


def _domain_junked(dom: str, exclude_pk: int | None) -> bool:
    junked = kept = 0
    qs = Message.objects.filter(from_addr__endswith="@" + dom).select_related("folder")
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    for m in qs.only("keywords", "folder__role", "seen", "flagged", "answered")[:300]:
        kws = m.keywords or []
        if "$NotJunk" in kws:
            return False
        if m.folder.role == FolderRole.JUNK or "$Junk" in kws:
            junked += 1
        elif m.folder.role != FolderRole.TRASH and (m.seen or m.flagged or m.answered):
            kept += 1
    return junked >= LEARN_DOMAIN and kept == 0


def record(message, rule: str, why: str) -> None:
    keep = [f for f in (message.risk_findings or []) if f.get("rule") != RULE]
    keep.append({"rule": RULE, "title": "Spam filter", "reason": why, "weight": 0, "verdict": "junk", "by": rule})
    message.risk_findings = keep
    message.save(update_fields=["risk_findings"])
