"""Reply templates and the attachments browser."""

from mail.models import Attachment, FolderRole, Message


# --- templates -------------------------------------------------------------------

def test_template_crud_and_sanitizing(api):
    r = api.post("/api/templates", {"name": "  Thanks ", "subject": "Re: hi\r\nBcc: x@evil.test",
                                    "bodyHtml": "<p>Thanks!</p><script>alert(1)</script><img src=x onerror=alert(1)>"})
    assert r.status_code == 200
    t = r.json()
    assert t["name"] == "Thanks"
    assert "\n" not in t["subject"] and "\r" not in t["subject"]
    assert "<script" not in t["bodyHtml"] and "onerror" not in t["bodyHtml"] and "Thanks!" in t["bodyHtml"]

    other = api.post("/api/templates", {"name": "Address", "bodyHtml": "<p>Street 1</p>"}).json()
    api.post(f"/api/templates/{other['id']}")  # used once -> ranks first
    assert [x["name"] for x in api.get("/api/templates").json()] == ["Address", "Thanks"]

    assert api.patch(f"/api/templates/{t['id']}", {"name": "Thank you"}).json()["name"] == "Thank you"
    assert api.patch(f"/api/templates/{t['id']}", {"name": "  "}).status_code == 400
    assert api.post("/api/templates", {"bodyHtml": "<p>x</p>"}).status_code == 400  # needs a name
    assert api.post("/api/templates", {"name": "big", "bodyHtml": "x" * 200_000}).status_code == 400
    assert api.delete(f"/api/templates/{t['id']}").status_code == 200
    assert api.patch(f"/api/templates/{t['id']}", {"name": "gone"}).status_code == 404


def test_templates_need_login(db, anon):
    assert anon.get("/api/templates").status_code == 401
    assert anon.get("/api/attachments").status_code == 401


# --- attachments browser --------------------------------------------------------

def test_files_list_and_filters(loaded, api):
    files = api.get("/api/attachments").json()["files"]
    names = {f["filename"] for f in files}
    assert names, "corpus has attachments"
    assert all(not a.inline for a in Attachment.objects.filter(pk__in=[f["id"] for f in files]))
    kinds = {f["kind"] for f in files}
    assert "image" in kinds and "pdf" in kinds

    images = api.get("/api/attachments", kind="image").json()["files"]
    assert images and all(f["kind"] == "image" for f in images)
    pdfs = api.get("/api/attachments", kind="pdf").json()["files"]
    assert pdfs and all(f["kind"] == "pdf" for f in pdfs)
    assert all(f["previewable"] is False for f in pdfs)  # never rendered inline

    by_sender = api.get("/api/attachments", q="alice@friends").json()["files"]
    assert by_sender and all(f["from"]["addr"] == "alice@friends.test" for f in by_sender)
    assert api.get("/api/attachments", q="no-such-file-anywhere").json()["files"] == []


def test_files_skip_trash_and_dedupe(loaded, api):
    first = api.get("/api/attachments").json()["files"]
    m = Message.objects.get(pk=first[0]["messageId"])
    m.folder = m.folder.__class__.objects.get(role=FolderRole.TRASH)
    m.save()
    after = api.get("/api/attachments").json()["files"]
    assert first[0]["id"] not in {f["id"] for f in after}
    keys = [(f["messageId"], f["filename"]) for f in after]
    assert len(keys) == len(set(keys))


def test_files_pagination(loaded, api):
    msg = Message.objects.filter(attachments__inline=False).first()
    for i in range(70):
        Attachment.objects.create(message=msg, part_index=100 + i, filename=f"bulk-{i}.txt", content_type="text/plain", size=10)
    r1 = api.get("/api/attachments").json()
    assert len(r1["files"]) == 60 and r1["next"]
    r2 = api.get("/api/attachments", before=r1["next"]).json()
    ids1, ids2 = {f["id"] for f in r1["files"]}, {f["id"] for f in r2["files"]}
    assert ids2 and not ids1 & ids2
