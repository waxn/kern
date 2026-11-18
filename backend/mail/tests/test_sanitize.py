import re

from mail.parsing import parse_message
from mail.sanitize import linkify_text, sanitize_html
from mail.testing import corpus

HOSTILE = corpus.HOSTILE_HTML


def clean(html, **kw):
    return sanitize_html(html, message_pk=1, **kw)


def assert_inert(out: str):
    # Inside <style> the content is CSS, not markup; it must not contain "<"
    # (which could close the element), then it's ignored for the checks below.
    for css in re.findall(r"<style[^>]*>(.*?)</style>", out, re.S | re.I):
        assert "<" not in css, out
        for bad in ("expression(", "@import", "javascript:", "-moz-binding", "evil.example", "tracker.example"):
            assert bad not in css.lower(), out
    out = re.sub(r"(<style[^>]*>).*?(</style>)", r"\1\2", out, flags=re.S | re.I)
    low = out.lower()
    for bad in ("<script", "javascript:", "vbscript:", "<iframe", "<object", "<embed", "<form", "<input",
                "<svg", "<math", "<base", "<meta", "<link", "<template", "<noscript", "expression(",
                "@import", "-moz-binding", "behavior:", "data:text/html", "srcset", "<button"):
        assert bad not in low, f"{bad!r} survived:\n{out}"
    # No event handler attributes anywhere.
    assert not re.search(r"\son[a-z]+\s*=", low), out
    # No remote fetches unless explicitly proxied.
    assert "tracker.example" not in low
    assert "evil.example" not in low


def test_hostile_corpus_is_neutralised():
    res = clean(HOSTILE)
    assert_inert(res.html)
    assert "Hostile HTML test" in res.html
    assert "should vanish" not in res.html  # <title> content dropped
    assert res.remote_images >= 3


def test_links_open_safely():
    out = clean('<a href="https://safe.example/x" target="_self" rel="opener">x</a>').html
    assert 'target="_blank"' in out
    assert "noopener" in out and "noreferrer" in out
    assert "opener\"" not in out.replace("noopener", "")


def test_relative_and_odd_scheme_links_dropped():
    out = clean('<a href="/rel">r</a><a href="file:///etc/passwd">f</a><a href="mailto:a@b.test">m</a>').html
    assert "/rel" not in out and "file:" not in out
    assert "mailto:a@b.test" in out


def test_images_blocked_then_proxied():
    html = '<img src="https://img.example/a.png"><div style="background:url(https://img.example/b.png)">x</div>'
    blocked = clean(html)
    assert "img.example" not in blocked.html
    assert blocked.remote_images == 2
    loaded = clean(html, load_images=True)
    assert loaded.html.count("/api/img?u=https%3A%2F%2Fimg.example") == 2
    assert "&s=" in loaded.html or "&amp;s=" in loaded.html


def test_cid_images_point_at_attachment_endpoint():
    out = clean('<img src="cid:logo@x">', cid_map={"logo@x": 42}).html
    assert "/api/messages/1/attachments/42?inline=1" in out
    unknown = clean('<img src="cid:nope@x">').html
    assert "cid:" not in unknown


def test_style_block_cannot_break_out():
    out = clean("<style>p{color:red}</style><p>x</p>").html
    assert "<style>" in out and "color:red" in out
    out2 = clean("<style>a{} </style><script>alert(1)</script>").html
    assert "<script" not in out2


def test_mxss_classics():
    payloads = [
        '<noscript><p title="</noscript><img src=x onerror=alert(1)>">',
        "<math><mtext><table><mglyph><style><img src=x onerror=alert(1)>",
        "<svg><p><style><img src=x onerror=alert(1)></style></p></svg>",
        '<form><math><mtext></form><form><mglyph><style></math><img src onerror=alert(1)>',
        "<img src=x:alert(1) onerror=eval(src)>",
        '<a href="&#106;avascript:alert(1)">x</a>',
        '<a href="jav&#x09;ascript:alert(1)">x</a>',
        "<div style=\"background:url('javascript:alert(1)')\">x</div>",
        "<<script>script>alert(1)<</script>/script>",
        '<img """><script>alert(1)</script>">',
    ]
    for pl in payloads:
        out = clean(pl).html
        assert_inert(out)


def test_every_corpus_html_is_inert():
    for item in corpus.build():
        pm = parse_message(item.raw)
        if pm.html:
            assert_inert(clean(pm.html).html)


def test_linkify_text_escapes():
    out = linkify_text('<b>hi</b> see https://x.example/a?b=1&c=2. "quote"')
    assert "<b>" not in out
    assert 'href="https://x.example/a?b=1&amp;c=2"' in out
    assert "&quot;quote&quot;" in out or "\"quote\"" not in out.split(">")[-1]


def test_email_cannot_smuggle_our_own_relative_urls():
    out = clean('<img src="/api/messages/9/attachments/1?inline=1"><a href="/api/img?u=x&s=y">a</a>'
                '<img src="//api/img?u=x">').html
    assert "/api/" not in out
