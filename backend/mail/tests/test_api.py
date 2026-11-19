import email

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from mail.models import Draft, Folder, FolderRole, Message, OutboxOp, Thread
from mail.outbox import Executor

pytestmark = pytest.mark.django_db


def inbox_view():
    return f"folder:{Folder.objects.get(role=FolderRole.INBOX).pk}"


def test_folders_and_thread_list(loaded, api, monkeypatch):
    from mail.api import views

    monkeypatch.setattr(views, "PAGE", 10)
    data = api.get("/api/folders").json()
    roles = [f["role"] for f in data["folders"]]
    assert roles[0] == "inbox"
    r = api.get("/api/threads", view=inbox_view()).json()
    assert len(r["threads"]) == 10 and r["next"]
    r2 = api.get("/api/threads", view=inbox_view(), cursor=r["next"]).json()
    ids1 = {t["id"] for t in r["threads"]}
    assert not ids1 & {t["id"] for t in r2["threads"]}
    dates = [t["lastDate"] for t in r["threads"]]
    assert dates == sorted(dates, reverse=True)


def test_unread_filter(loaded, api):
    view = inbox_view()
    read = Message.objects.get(subject="Lunch on Friday?").thread
    api.post("/api/threads/actions", {"ids": [read.pk], "action": "read"})
    everything = api.get("/api/threads", view=view).json()["threads"]
    unread = api.get("/api/threads", view=view, unread="1").json()["threads"]
    assert unread and len(unread) < len(everything)
    assert all(t["unread"] > 0 for t in unread)
    assert read.pk not in {t["id"] for t in unread}


def test_thread_detail_collapses_identical_copies(loaded, api):
    t = Message.objects.filter(subject="Filed copy").first().thread
    d = api.get(f"/api/threads/{t.pk}").json()
    assert len(d["messages"]) == 1


def test_thread_detail_keeps_different_duplicates(loaded, api):
    ids = set(Message.objects.filter(message_id="duplicate@work.test").values_list("thread_id", flat=True))
    total = sum(len(api.get(f"/api/threads/{tid}").json()["messages"]) for tid in ids)
    assert total == 2


def test_body_is_sanitized_and_images_blocked(loaded, api):
    m = Message.objects.get(subject="Hostile HTML")
    b = api.get(f"/api/messages/{m.pk}/body").json()
    assert "<script" not in b["html"] and "tracker.example" not in b["html"]
    assert b["remoteImages"] > 0 and not b["imagesLoaded"]
    b2 = api.get(f"/api/messages/{m.pk}/body", images="1").json()
    assert "/api/mail/img?u=" in b2["html"] and b2["imagesLoaded"]


def test_message_headers(loaded, api):
    m = Message.objects.get(message_id="forged@evil.example")
    h = api.get(f"/api/messages/{m.pk}/headers").json()["headers"]
    assert h.startswith("Authentication-Results: mx.manifest.test; spf=fail")
    assert "Click here." not in h  # body excluded


def test_plain_text_body_is_escaped(loaded, api):
    m = Message.objects.get(subject="Lunch on Friday?")
    b = api.get(f"/api/messages/{m.pk}/body").json()
    assert b["html"] is None and "https://maps.example/place" in b["textHtml"]


def test_attachment_download_is_safe(loaded, api):
    m = Message.objects.get(subject="Files for you")
    atts = {a.filename: a for a in m.attachments.all()}
    pdf = atts["€ rates 2026.pdf"]
    r = api.get(f"/api/messages/{m.pk}/attachments/{pdf.pk}", inline="1")
    assert r["Content-Type"] == "application/octet-stream"  # never rendered inline
    assert r["Content-Disposition"].startswith("attachment")
    assert "sandbox" in r["Content-Security-Policy"]
    assert r.content.startswith(b"%PDF")
    png = next(a for a in m.attachments.all() if a.content_id)
    r2 = api.get(f"/api/messages/{m.pk}/attachments/{png.pk}", inline="1")
    assert r2["Content-Type"] == "image/png" and r2["Content-Disposition"].startswith("inline")


def test_search(loaded, api):
    r = api.get("/api/threads", q="lisbon").json()
    assert len(r["threads"]) == 1
    r = api.get("/api/threads", q="from:alice").json()
    assert len(r["threads"]) >= 2
    r = api.get("/api/threads", q="has:attachment").json()
    subjects = {t["subject"] for t in r["threads"]}
    assert "Files for you" in subjects
    r = api.get("/api/threads", q="risk:high").json()
    assert any("limited" in t["subject"] for t in r["threads"])
    r = api.get("/api/threads", q="in:sent trip").json()
    assert len(r["threads"]) == 1


def test_thread_actions_queue_server_changes(loaded, api):
    t = Message.objects.get(subject="Lunch on Friday?").thread
    inbox = Folder.objects.get(role=FolderRole.INBOX)
    assert api.post("/api/threads/actions", {"ids": [t.pk], "action": "star"}).status_code == 200
    t.refresh_from_db()
    assert t.starred
    api.post("/api/threads/actions", {"ids": [t.pk], "action": "archive", "context": inbox.pk})
    assert not Message.objects.filter(thread=t, folder=inbox).exists()
    kinds = list(OutboxOp.objects.values_list("kind", flat=True))
    assert "flags" in kinds and "move" in kinds


def test_spam_api_guard(loaded, api):
    m = Message.objects.get(subject="Lunch on Friday?")
    m.from_addr = "someone@outlook.com"
    m.save()
    r = api.post("/api/threads/actions", {"ids": [m.thread_id], "action": "spam", "block": "domain",
                                          "context": m.folder_id})
    assert r.status_code == 400 and "shared" in r.json()["detail"]
    check = api.get("/api/blocklist/check", addr="someone@outlook.com").json()
    assert check["domainBlockAllowed"] is False


def test_compose_reply_send_and_undo(loaded, api, server, settings):
    settings.MAIL = {**settings.MAIL, "SEND_UNDO_SECONDS": 30}
    m = Message.objects.get(message_id="trip2@friends.test")
    pre = api.get("/api/compose/prefill", message=m.pk, mode="reply_all").json()
    assert pre["subject"] == "Re: Re: Trip planning"
    assert pre["to"][0]["addr"] == "alice@friends.test"
    assert "blockquote" in pre["body_html"]
    d = api.post("/api/drafts", {"mode": "reply_all", "inReplyTo": m.pk, "to": pre["to"], "cc": pre["cc"],
                                 "subject": pre["subject"], "bodyHtml": "<p>Booked!</p><script>x</script>" + pre["body_html"]}).json()
    assert "<script" not in d["bodyHtml"]
    up = api.upload(f"/api/drafts/{d['id']}/uploads", [SimpleUploadedFile("plan.txt", b"day 1: tram 28")])
    assert up.status_code == 200
    sent = api.post(f"/api/drafts/{d['id']}/send").json()
    assert sent["status"] == "queued"
    undo = api.post(f"/api/drafts/{d['id']}/undo")
    assert undo.status_code == 200 and undo.json()["status"] == "editing"
    settings.MAIL = {**settings.MAIL, "SEND_UNDO_SECONDS": 0}
    api.post(f"/api/drafts/{d['id']}/send")
    from mail.imap.fake import FakeSender

    snd = FakeSender()
    ex = Executor(server, snd)
    ex.run_pending()
    ex.run_pending()  # append to Sent + \\Answered
    assert len(snd.sent) == 1
    env_from, rcpts, raw = snd.sent[0]
    assert rcpts == ["alice@friends.test"]
    parsed = email.message_from_bytes(raw)
    assert parsed["In-Reply-To"] == "<trip2@friends.test>"
    assert "<trip0@manifest.test>" in parsed["References"]
    assert any(p.get_filename() == "plan.txt" for p in parsed.walk())
    assert Draft.objects.get(pk=d["id"]).status == "sent"
    m.refresh_from_db()
    assert m.answered
    # The sent copy was appended to Sent and joined the conversation.
    sent_copy = Message.objects.get(message_id=Draft.objects.get(pk=d["id"]).message_id)
    assert sent_copy.folder.role == "sent" and sent_copy.thread_id == m.thread_id


def test_header_injection_rejected(loaded, api):
    r = api.post("/api/drafts", {"to": ["victim@x.test\r\nBcc: evil@x.test"], "subject": "hi"})
    assert r.status_code == 400


def test_labels_roundtrip_as_keywords(loaded, api, server):
    lb = api.post("/api/labels", {"name": "Résumés & CVs"}).json()
    t = Message.objects.get(subject="Lunch on Friday?").thread
    api.post("/api/threads/actions", {"ids": [t.pk], "action": "label_add", "label": lb["id"]})
    Executor(server).run_pending()
    m = Message.objects.filter(thread=t, folder__role="inbox").first()
    kw = [f for f in server.flags_of("INBOX", m.uid) if f.startswith("$MLX_")]
    assert kw
    from mail.labels import name_for

    assert name_for(kw[0]) == "Résumés & CVs"
    assert lb["id"] in Thread.objects.get(pk=t.pk).label_ids


def test_image_proxy_requires_signature(api):
    assert api.get("/api/img", u="https://x.example/a.png", s="bad").status_code == 403


def test_mark_folder_read(loaded, api, server):
    inbox = Folder.objects.get(role=FolderRole.INBOX)
    unread = Message.objects.filter(folder=inbox, seen=False).count()
    assert unread > 0
    r = api.post(f"/api/folders/{inbox.pk}/read-all").json()
    assert r["count"] == unread
    assert not Message.objects.filter(folder=inbox, seen=False).exists()
    Executor(server).run_pending()
    assert all("\\Seen" in m.flags for m in server.boxes["INBOX"].msgs.values())


def test_attachment_previews(loaded, api):
    m = Message.objects.get(subject="Trip files")
    t = api.get(f"/api/threads/{m.thread_id}").json()
    msg = next(x for x in t["messages"] if x["id"] == m.pk)
    kinds = {a["filename"]: a["preview"] for a in msg["attachments"]}
    assert kinds == {"itinerary.pdf": "pdf", "itinerary.html": "html", "budget.csv": "text", "voice note.wav": "audio"}
    atts = {a.filename: a for a in m.attachments.all()}

    # Audio is played inline, with its real type (from the name: it came as octet-stream) and seeking.
    wav = atts["voice note.wav"]
    r = api.get(f"/api/messages/{m.pk}/attachments/{wav.pk}", inline="1")
    assert r["Content-Type"] == "audio/wav" and r["Content-Disposition"].startswith("inline")
    assert r["Accept-Ranges"] == "bytes" and r["X-Content-Type-Options"] == "nosniff"
    part = api.c.get(f"/api/mail/messages/{m.pk}/attachments/{wav.pk}?inline=1", HTTP_RANGE="bytes=8-15")
    assert part.status_code == 206 and part.content == b"WAVEfmt " and part["Content-Range"].startswith("bytes 8-15/")

    # PDFs and HTML are still never rendered by the browser on our origin.
    for name in ("itinerary.pdf", "itinerary.html"):
        r = api.get(f"/api/messages/{m.pk}/attachments/{atts[name].pk}", inline="1")
        assert r["Content-Type"] == "application/octet-stream" and r["Content-Disposition"].startswith("attachment")

    # HTML goes through the email sanitizer: no script, head styles kept, remote images blocked until asked.
    h = api.get(f"/api/messages/{m.pk}/attachments/{atts['itinerary.html'].pk}/html").json()
    assert "Lisbon itinerary" in h["html"] and "color:#2f4ad0" in h["html"]
    assert "script" not in h["html"] and "pwned" not in h["html"] and "img.example" not in h["html"]
    assert h["remoteImages"] == 1 and not h["imagesLoaded"]
    h2 = api.get(f"/api/messages/{m.pk}/attachments/{atts['itinerary.html'].pk}/html", images="1").json()
    assert "/api/mail/img?u=" in h2["html"] and h2["imagesLoaded"]
    assert api.get(f"/api/messages/{m.pk}/attachments/{atts['budget.csv'].pk}/html").status_code == 400


def test_files_page_media_kind(loaded, api):
    r = api.get("/api/attachments", kind="media").json()
    assert [f["filename"] for f in r["files"]] == ["voice note.wav"]
    assert r["files"][0]["kind"] == "media" and r["files"][0]["preview"] == "audio"
    other = api.get("/api/attachments", kind="other").json()
    assert "voice note.wav" not in [f["filename"] for f in other["files"]]
