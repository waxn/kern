"""Mail data model.

The IMAP server is the source of truth. These tables are a local index/cache
that can be rebuilt from the server (plus raw message blobs on disk).

Identity of a stored message is (folder, uidvalidity, uid). Message-ID is
NOT unique and is only used for threading and for linking notes/tasks.
"""

from __future__ import annotations

from django.db import models


class FolderRole(models.TextChoices):
    NONE = "", "None"
    INBOX = "inbox", "Inbox"
    SENT = "sent", "Sent"
    DRAFTS = "drafts", "Drafts"
    JUNK = "junk", "Junk"
    TRASH = "trash", "Trash"
    ARCHIVE = "archive", "Archive"
    SNOOZED = "snoozed", "Snoozed"
    ALL = "all", "All mail"


class Folder(models.Model):
    name = models.CharField(max_length=512, unique=True)  # decoded IMAP mailbox name
    delimiter = models.CharField(max_length=4, blank=True, default="/")
    role = models.CharField(max_length=16, choices=FolderRole.choices, blank=True, default="")
    selectable = models.BooleanField(default=True)
    # Created locally (e.g. "Archive") and not yet on the server.
    needs_create = models.BooleanField(default=False)
    uidvalidity = models.BigIntegerField(null=True, blank=True)
    uidnext = models.BigIntegerField(null=True, blank=True)
    highestmodseq = models.BigIntegerField(null=True, blank=True)
    initial_sync_done = models.BooleanField(default=False)
    last_sync = models.DateTimeField(null=True, blank=True)
    exists_on_server = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def display_name(self) -> str:
        if self.role == FolderRole.INBOX:
            return "Inbox"
        leaf = self.name.split(self.delimiter)[-1] if self.delimiter else self.name
        return leaf


class Blob(models.Model):
    """Raw RFC 822 bytes, content-addressed. Stored gzip'd on disk under
    MAILSTORE_DIR; see mail/store.py."""

    sha256 = models.CharField(max_length=64, primary_key=True)
    size = models.IntegerField()
    created = models.DateTimeField(auto_now_add=True)


class Label(models.Model):
    name = models.CharField(max_length=128, unique=True)
    color = models.CharField(max_length=16, blank=True, default="")
    # IMAP keyword that represents this label on the server.
    keyword = models.CharField(max_length=200, unique=True)

    class Meta:
        ordering = ["name"]


class Thread(models.Model):
    subject = models.TextField(blank=True, default="")
    last_date = models.DateTimeField(null=True, db_index=True)
    message_count = models.IntegerField(default=0)
    unread_count = models.IntegerField(default=0)
    starred = models.BooleanField(default=False)
    has_attachments = models.BooleanField(default=False)
    participants = models.JSONField(default=list)  # [{"name":..,"addr":..}]
    snippet = models.TextField(blank=True, default="")
    risk_level = models.CharField(max_length=8, blank=True, default="")
    label_ids = models.JSONField(default=list)

    class Meta:
        indexes = [models.Index(fields=["-last_date", "-id"])]


class Message(models.Model):
    # Where the message is shown. Differs from server_folder only while a
    # move is waiting to be written back (see mail/outbox.py).
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name="messages")
    # Where the message really is on the server: (server_folder, uidvalidity,
    # uid). uid is NULL right after a move whose new UID isn't known yet.
    server_folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name="server_messages")
    uid = models.BigIntegerField(null=True, blank=True)
    uidvalidity = models.BigIntegerField(null=True, blank=True)
    blob = models.ForeignKey(Blob, on_delete=models.PROTECT, related_name="messages")
    thread = models.ForeignKey(Thread, on_delete=models.SET_NULL, null=True, related_name="messages")

    message_id = models.CharField(max_length=998, blank=True, default="")
    # message_id, or "synthetic:<sha256>" when the header is missing.
    message_key = models.CharField(max_length=998, db_index=True)
    in_reply_to = models.CharField(max_length=998, blank=True, default="")
    references = models.JSONField(default=list)

    subject = models.TextField(blank=True, default="")
    subject_norm = models.CharField(max_length=512, blank=True, default="", db_index=True)
    from_name = models.CharField(max_length=512, blank=True, default="")
    from_addr = models.CharField(max_length=512, blank=True, default="", db_index=True)
    to_addrs = models.JSONField(default=list)
    cc_addrs = models.JSONField(default=list)
    bcc_addrs = models.JSONField(default=list)
    reply_to = models.JSONField(default=list)
    search_recipients = models.TextField(blank=True, default="")
    attachment_names = models.TextField(blank=True, default="")

    date = models.DateTimeField(null=True, blank=True)  # Date: header (if sane)
    internal_date = models.DateTimeField(null=True, blank=True)
    sort_date = models.DateTimeField(db_index=True)

    seen = models.BooleanField(default=False)
    flagged = models.BooleanField(default=False)
    answered = models.BooleanField(default=False)
    is_draft = models.BooleanField(default=False)
    keywords = models.JSONField(default=list)  # other IMAP keywords
    labels = models.ManyToManyField(Label, blank=True, related_name="messages")

    size = models.IntegerField(default=0)
    has_attachments = models.BooleanField(default=False)
    has_html = models.BooleanField(default=False)
    snippet = models.CharField(max_length=300, blank=True, default="")
    body_text = models.TextField(blank=True, default="")  # for search + plain view
    headers = models.JSONField(default=dict)  # selected headers (list-id, etc.)
    parse_defects = models.JSONField(default=list)

    # Phishing risk: see mail/risk/. findings = [{"rule","reason","weight"}]
    risk_level = models.CharField(max_length=8, blank=True, default="")
    risk_score = models.IntegerField(default=0)
    risk_findings = models.JSONField(default=list)
    auth_results = models.JSONField(default=dict)
    # Which pipeline stages (name -> version) have processed this message.
    pipeline = models.JSONField(default=dict)
    routed_by_block = models.ForeignKey(
        "BlockRule", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["server_folder", "uidvalidity", "uid"], name="message_server_identity"),
        ]
        indexes = [
            models.Index(fields=["thread", "sort_date"]),
            models.Index(fields=["folder", "-sort_date"]),
            models.Index(fields=["server_folder", "uid"]),
        ]


class ThreadFolder(models.Model):
    """Which folders a conversation has messages in: a small index kept by
    threads.refresh_thread(), so a folder's list ("Inbox", newest first) and
    its counts are an index range read instead of a scan over every thread
    and message. Rebuildable from Message at any time (rebuild_thread_index)."""

    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="in_folders")
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name="thread_rows")
    last_date = models.DateTimeField(null=True)  # copy of Thread.last_date: the sort key
    unread = models.BooleanField(default=False)  # an unseen message of the thread is in this folder

    class Meta:
        constraints = [models.UniqueConstraint(fields=["folder", "thread"], name="threadfolder_unique")]
        indexes = [
            models.Index(fields=["folder", "-last_date", "-thread"], name="threadfolder_list"),
            models.Index(fields=["folder", "unread", "-last_date", "-thread"], name="threadfolder_unread"),
            models.Index(fields=["thread"], name="threadfolder_thread"),
        ]


class MessageReference(models.Model):
    """Reverse index of References/In-Reply-To for threading."""

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="refs")
    key = models.CharField(max_length=998, db_index=True)


class Attachment(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="attachments")
    part_index = models.IntegerField()  # position in mail.parsing.iter_leaf_parts
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255)
    size = models.IntegerField(default=0)
    content_id = models.CharField(max_length=512, blank=True, default="")
    inline = models.BooleanField(default=False)

    class Meta:
        ordering = ["part_index"]


class Correspondent(models.Model):
    """Everyone you've received mail from or sent mail to. Used by the risk
    rules (first-time sender, contact impersonation) and autocomplete."""

    address = models.CharField(max_length=512, unique=True)
    name = models.CharField(max_length=512, blank=True, default="")
    received_count = models.IntegerField(default=0)
    sent_count = models.IntegerField(default=0)
    first_seen = models.DateTimeField(null=True)
    last_seen = models.DateTimeField(null=True)


class BlockKind(models.TextChoices):
    ADDRESS = "address", "Address"
    DOMAIN = "domain", "Domain"


class BlockRule(models.Model):
    kind = models.CharField(max_length=8, choices=BlockKind.choices)
    value = models.CharField(max_length=512)
    note = models.CharField(max_length=512, blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)
    hits = models.IntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["kind", "value"], name="block_unique")]
        ordering = ["-created"]


class TrustedImageSender(models.Model):
    """Senders whose remote images load automatically (via the proxy)."""

    address = models.CharField(max_length=512, unique=True)
    created = models.DateTimeField(auto_now_add=True)


class OpStatus(models.TextChoices):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OutboxOp(models.Model):
    """A change to write back to the server (two-way sync). Executed in order
    by the sync worker; see mail/outbox.py."""

    kind = models.CharField(max_length=32)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=OpStatus.choices, default=OpStatus.PENDING, db_index=True)
    attempts = models.IntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    not_before = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    finished = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]


class ChangeEvent(models.Model):
    """Append-only change feed, streamed to the browser over SSE."""

    kind = models.CharField(max_length=32)
    data = models.JSONField(default=dict)
    created = models.DateTimeField(auto_now_add=True, db_index=True)


class Upload(models.Model):
    """An attachment uploaded for a draft. Stored under MAILSTORE_DIR/uploads."""

    draft = models.ForeignKey("Draft", on_delete=models.CASCADE, null=True, blank=True, related_name="uploads")
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255)
    size = models.IntegerField()
    sha256 = models.CharField(max_length=64)
    created = models.DateTimeField(auto_now_add=True)


class DraftStatus(models.TextChoices):
    EDITING = "editing"
    QUEUED = "queued"  # inside the undo-send window
    SCHEDULED = "scheduled"  # "send later": waits for send_at
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


class Draft(models.Model):
    mode = models.CharField(max_length=16, default="new")  # new|reply|reply_all|forward
    to_addrs = models.JSONField(default=list)
    cc_addrs = models.JSONField(default=list)
    bcc_addrs = models.JSONField(default=list)
    subject = models.TextField(blank=True, default="")
    body_html = models.TextField(blank=True, default="")
    in_reply_to = models.ForeignKey(Message, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    references = models.JSONField(default=list)
    in_reply_to_key = models.CharField(max_length=998, blank=True, default="")
    # Message-ID used for every server copy of this draft and the final send.
    message_id = models.CharField(max_length=998)
    server_folder = models.ForeignKey(Folder, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    server_uidvalidity = models.BigIntegerField(null=True, blank=True)
    server_uid = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=DraftStatus.choices, default=DraftStatus.EDITING)
    send_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    forward_attachments_of = models.ForeignKey(
        Message, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Attachment ids of forward_attachments_of to include.
    forward_attachment_ids = models.JSONField(default=list)
    # "Nudge me if no reply by ..." chosen in the composer.
    followup_at = models.DateTimeField(null=True, blank=True)
    # Send as another address of yours (MailIdentity); empty: the account's own address.
    from_addr = models.CharField(max_length=320, blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)


class SnoozeStatus(models.TextChoices):
    ACTIVE = "active"
    WOKEN = "woken"
    CANCELLED = "cancelled"


class Snooze(models.Model):
    """A snoozed conversation. Its messages wait in the server's "Snoozed"
    folder until wake_at, then return to the Inbox as unread. Messages are
    named by Message-ID (message_keys) so the snooze survives resyncs."""

    thread = models.ForeignKey(Thread, on_delete=models.SET_NULL, null=True, blank=True, related_name="snoozes")
    message_keys = models.JSONField(default=list)
    subject = models.TextField(blank=True, default="")
    wake_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=16, choices=SnoozeStatus.choices, default=SnoozeStatus.ACTIVE, db_index=True)
    created = models.DateTimeField(auto_now_add=True)
    woken_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["wake_at"]


class FollowUpStatus(models.TextChoices):
    WAITING = "waiting"   # waiting for a reply until due_at
    NUDGED = "nudged"     # no reply by due_at: shown to you
    DONE = "done"         # replied, or you dismissed it
    CANCELLED = "cancelled"


class FollowUp(models.Model):
    """"Nudge me if nobody replies": watches a message you sent and, if no one
    else has written in that conversation by due_at, brings it to your
    attention. Purely local; nothing changes on the mail server."""

    thread = models.ForeignKey(Thread, on_delete=models.SET_NULL, null=True, blank=True, related_name="followups")
    message_key = models.CharField(max_length=998, db_index=True)  # the message you sent
    subject = models.TextField(blank=True, default="")
    recipients = models.JSONField(default=list)
    sent_at = models.DateTimeField()
    due_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=16, choices=FollowUpStatus.choices, default=FollowUpStatus.WAITING, db_index=True)
    nudged_at = models.DateTimeField(null=True, blank=True)
    # The Kern task that stands for this follow-up (mail/taskbridge.py).
    task_id = models.CharField(max_length=36, blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_at"]


class Mute(models.Model):
    """A muted conversation: new messages in it skip the Inbox (archived and
    marked read). Remembered by Message-ID so it survives resyncs."""

    message_keys = models.JSONField(default=list)
    thread = models.ForeignKey(Thread, on_delete=models.SET_NULL, null=True, blank=True, related_name="mutes")
    subject = models.TextField(blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)


class Shipment(models.Model):
    """A package found in shipping emails (mail/packages.py). Status comes
    from the newest email that mentions the tracking number."""

    carrier = models.CharField(max_length=32)
    number = models.CharField(max_length=64)
    status = models.CharField(max_length=32, default="in_transit")
    status_at = models.DateTimeField(null=True, blank=True)
    expected = models.DateField(null=True, blank=True)
    expected_text = models.CharField(max_length=100, blank=True, default="")
    merchant = models.CharField(max_length=200, blank=True, default="")
    subject = models.TextField(blank=True, default="")
    message_keys = models.JSONField(default=list)
    thread = models.ForeignKey(Thread, on_delete=models.SET_NULL, null=True, blank=True, related_name="shipments")
    hidden = models.BooleanField(default=False)
    # Live tracking (mail/tracking.py): the carrier's latest scans.
    live = models.BooleanField(default=False)
    live_events = models.JSONField(default=list)
    location = models.CharField(max_length=120, blank=True, default="")
    # For the map: {"origin": str, "destination": str, "points": [[lat, lon, place], ...]} oldest first.
    route = models.JSONField(default=dict)
    checked_at = models.DateTimeField(null=True, blank=True)
    # Why the last live lookup found nothing ("UPS only answers a browser…"); "" when it worked.
    track_note = models.CharField(max_length=300, blank=True, default="")
    first_seen = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["carrier", "number"], name="shipment_unique")]
        ordering = ["-status_at"]


class Template(models.Model):
    """A saved reply ("canned response"). Body is sanitized compose HTML."""

    name = models.CharField(max_length=120)
    subject = models.CharField(max_length=500, blank=True, default="")
    body_html = models.TextField(blank=True, default="")
    uses = models.IntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]


class Preferences(models.Model):
    """Singleton (pk=1): settings that should follow you to every device.
    See mail/preferences.py for the keys and their defaults."""

    data = models.JSONField(default=dict)
    updated = models.DateTimeField(auto_now=True)


class WorkerStatus(models.Model):
    """Singleton heartbeat written by the sync worker (pk=1)."""

    state = models.CharField(max_length=32, default="starting")
    detail = models.TextField(blank=True, default="")
    last_error = models.TextField(blank=True, default="")
    last_error_at = models.DateTimeField(null=True, blank=True)
    heartbeat = models.DateTimeField(null=True, blank=True)
    capabilities = models.JSONField(default=list)


class MailAccount(models.Model):
    """This user's IMAP/SMTP account (a single row, pk=1). The password is
    encrypted with kern/secretbox.py; see mail/account.py."""

    address = models.CharField(max_length=320, blank=True, default="")  # also the From address
    login = models.CharField(max_length=320, blank=True, default="")  # IMAP/SMTP username if not the address
    from_name = models.CharField(max_length=200, blank=True, default="")
    aliases = models.JSONField(default=list)
    imap_host = models.CharField(max_length=255, blank=True, default="")
    imap_port = models.IntegerField(default=993)
    smtp_host = models.CharField(max_length=255, blank=True, default="")
    smtp_port = models.IntegerField(default=465)
    smtp_security = models.CharField(max_length=16, default="ssl")  # ssl | starttls
    tls_verify = models.BooleanField(default=True)
    server_saves_sent = models.BooleanField(default=False)
    authserv_id = models.CharField(max_length=255, blank=True, default="")
    password_enc = models.TextField(blank=True, default="")
    enabled = models.BooleanField(default=False)
    # Bumped on every change so the worker reconnects with the new settings.
    version = models.IntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)



class MailIdentity(models.Model):
    """Another address you send as ("Send mail as"), e.g. a Gmail address whose mail is
    forwarded to this mailbox. With its own SMTP server the message goes out through that
    server (so it's signed by that provider); without one it goes through the account's own
    server. Either way the sent copy is saved in this mailbox's Sent folder."""

    address = models.CharField(max_length=320, unique=True)
    name = models.CharField(max_length=200, blank=True, default="")
    smtp_host = models.CharField(max_length=255, blank=True, default="")
    smtp_port = models.IntegerField(default=465)
    smtp_security = models.CharField(max_length=16, default="ssl")  # ssl | starttls
    login = models.CharField(max_length=320, blank=True, default="")
    password_enc = models.TextField(blank=True, default="")
    tls_verify = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)


class GeoPlace(models.Model):
    """A scan location ("Malmö, Sweden") and where it is, so each place is looked up once."""

    name = models.CharField(max_length=200, unique=True)
    lat = models.FloatField(null=True)
    lon = models.FloatField(null=True)
    looked_up = models.DateTimeField(auto_now=True)
