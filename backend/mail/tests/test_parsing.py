from mail.parsing import (
    decode_bytes, decode_header_value, normalize_subject, parse_addresses, parse_message, parse_references,
)
from mail.testing import corpus

C = corpus.by_name()


def p(name):
    return parse_message(C[name].raw)


def test_every_corpus_message_parses_without_raising():
    for item in corpus.build():
        pm = parse_message(item.raw)
        assert isinstance(pm.subject, str)
        assert isinstance(pm.text, str)


def test_rfc2047_subject_and_name():
    pm = p("rfc2047")
    assert pm.subject.startswith("Grüße aus München")
    assert pm.from_name == "Jörg Müller"
    assert "Schöne Grüße — Jörg" in pm.text


def test_mislabeled_latin1_is_actually_utf8():
    # Valid UTF-8 labelled latin-1 is decoded as UTF-8 (no mojibake).
    pm = p("mislabeled-latin1")
    assert "Crème brûlée and café au lait — €4" in pm.text


def test_mislabeled_utf8_falls_back_to_cp1252():
    pm = p("mislabeled-utf8")
    assert "“Smart quotes”" in pm.text
    assert any(d.startswith("charset-fallback") for d in pm.defects)


def test_unknown_charset():
    pm = p("unknown-charset")
    assert "plain ascii" in pm.text


def test_raw_8bit_headers():
    pm = p("raw-8bit-utf8-headers")
    assert pm.subject == "Grüße — raw 8-bit"
    assert pm.from_name == "Jörg Müller"
    pm2 = p("raw-latin1-headers")
    assert pm2.subject == "Résumé attached"
    assert pm2.from_name == "René"


def test_malformed_encoded_words_do_not_crash():
    pm = p("malformed-2047")
    assert pm.subject  # something displayable
    assert pm.from_addr == "broken@friends.test"


def test_broken_base64_gives_best_effort_text():
    pm = p("broken-base64")
    assert isinstance(pm.text, str)


def test_missing_headers():
    pm = p("missing-headers")
    assert pm.message_id == ""
    assert pm.from_ == []
    assert pm.date is None
    assert "Who sent this?" in pm.text


def test_garbage_date_is_none():
    assert p("garbage-date").date is None


def test_attachments_and_cid_and_rfc2231():
    pm = p("attachments")
    names = [a.filename for a in pm.attachments]
    assert "€ rates 2026.pdf" in names
    cids = [a.content_id for a in pm.attachments if a.content_id]
    assert "logo123@x" in cids
    # Forwarded message is an attachment, and its body is NOT mixed into ours.
    assert any(a.content_type == "message/rfc822" for a in pm.attachments)
    assert "The original.eml" in names
    assert "Forwarded content" not in pm.text
    assert "See the logo" in pm.text


def test_deep_nesting_is_bounded():
    pm = p("deep-nesting")
    assert isinstance(pm.text, str)


def test_control_chars_removed_from_subject():
    pm = p("control-chars")
    assert "\x07" not in pm.subject
    assert "\x00" not in pm.text


def test_html_only_gets_text_for_search():
    pm = p("newsletter")
    assert "Our picks" in pm.text


def test_decode_header_value_variants():
    assert decode_header_value("=?iso-8859-1?q?caf=E9?=") == "café"
    assert decode_header_value("Hello =?utf-8?q?W=C3=B6rld?= foo") == "Hello Wörld foo"
    assert decode_header_value(None) == ""


def test_decode_bytes_never_fails():
    text, clean = decode_bytes(b"\xff\xfe\x00garbage", "no-such-charset")
    assert isinstance(text, str)


def test_addresses_with_commas_in_names():
    addrs = parse_addresses(['"Doe, John" <john@x.test>, jane@y.test'])
    assert [a["addr"] for a in addrs] == ["john@x.test", "jane@y.test"]
    assert addrs[0]["name"] == "Doe, John"


def test_references_are_capped():
    refs = parse_references(" ".join(f"<r{i}@x>" for i in range(500)))
    assert len(refs) == 60
    assert refs[0] == "r0@x" and refs[-1] == "r499@x"


def test_normalize_subject():
    assert normalize_subject("Re: RE: Fwd: [list] Hello  World") == "hello world"
    assert normalize_subject("AW: SV: Hej") == "hej"
