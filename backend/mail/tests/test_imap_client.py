from mail.imap import utf7
from mail.imap.base import FolderInfo, detect_role
from mail.imap.client import expand_set, parse_fetch, parse_list_response, uid_set


def test_utf7_roundtrip():
    for name in ["INBOX", "Entwürfe", "日本語", "A&B", "Gesendete Objekte", "Корзина"]:
        assert utf7.decode(utf7.encode(name)) == name
    assert utf7.decode("Entw&APw-rfe") == "Entwürfe"
    assert utf7.encode("A&B") == "A&-B"


def test_uid_sets():
    assert uid_set([1, 2, 3, 7, 9, 10]) == "1:3,7,9:10"
    assert expand_set(b"1:3,7") == [1, 2, 3, 7]


def test_parse_list():
    data = [
        b'(\\HasNoChildren) "/" INBOX',
        b'(\\HasNoChildren \\Sent) "/" "Sent Items"',
        b'(\\Noselect \\HasChildren) "." "[Gmail]"',
        (b'(\\HasNoChildren) "/" {8}', b"Entw&APw-"),
        b'(\\Junk) "/" "Spam \\"quoted\\""',
    ]
    folders = parse_list_response(data)
    names = [f.name for f in folders]
    assert names == ["INBOX", "Sent Items", "[Gmail]", "Entwü", 'Spam "quoted"']
    assert not folders[2].selectable
    assert detect_role(folders[1]) == "sent"
    assert detect_role(folders[4]) == "junk"
    assert detect_role(FolderInfo("Deleted Items", "/", [])) == "trash"


def test_parse_fetch_with_literal_and_trailing_items():
    data = [
        (b'1 (UID 42 FLAGS (\\Seen $Junk) INTERNALDATE "01-Oct-2026 09:00:00 +0000" BODY[] {5}', b"hello"),
        b")",
        (b'2 (UID 43 BODY[] {3}', b"abc"),
        b' FLAGS (\\Flagged) INTERNALDATE "02-Oct-2026 10:00:00 +0200")',
        b"3 (FLAGS (\\Deleted) UID 44)",  # unsolicited flag update, no body
    ]
    out = parse_fetch(data, want_body=True)
    assert [(u, f, b) for u, f, _, b, _ in out] == [(42, ["\\Seen", "$Junk"], b"hello"), (43, ["\\Flagged"], b"abc")]
    assert out[1][2].hour == 8  # converted to UTC
    flags = parse_fetch([b"1 (UID 5 FLAGS (\\Seen) MODSEQ (77))"], want_body=False)
    assert flags[0][0] == 5 and flags[0][4] == 77
