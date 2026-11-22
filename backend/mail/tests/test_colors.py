from mail import colors
from mail.sanitize import sanitize_html


def fit(html, theme="dark"):
    return sanitize_html(html, message_pk=1, theme=theme)


def test_parse_forms():
    assert colors.parse("#fff")[:3] == (1.0, 1.0, 1.0)
    assert colors.parse("#000000") == (0.0, 0.0, 0.0, 1.0)
    assert colors.parse("White")[:3] == (1.0, 1.0, 1.0)
    assert colors.parse("rgb(255, 0, 0)")[:3] == (1.0, 0.0, 0.0)
    assert colors.parse("rgba(0,0,0,0)")[3] == 0
    assert colors.parse("hsl(0, 0%, 100%)")[:3] == (1.0, 1.0, 1.0)
    assert colors.parse("rgb(0 0 0 / 50%)")[3] == 0.5
    assert colors.parse("nonsense") is None
    assert colors.parse("#12") is None


LIGHT_NEWSLETTER = """
<table width="100%" bgcolor="#f4f4f4"><tr><td>
  <table bgcolor="#ffffff" style="border:1px solid #e0e0e0">
    <tr><td style="color:#222222">Hello <a href="https://x.example" style="color:#1a0dab">link</a></td></tr>
    <tr><td style="background-color:#e8f0fe;color:#333">Tip box</td></tr>
    <tr><td style="background:#1a73e8;color:#ffffff">Button</td></tr>
  </table>
</td></tr></table>"""


def test_light_email_on_dark_page():
    res = fit(LIGHT_NEWSLETTER)
    out = res.html.lower()
    assert res.colors == "adapted"
    # White and light grey pages are gone: Kern's background shows through.
    assert "bgcolor" not in out
    # Dark text is light now, keeping its hue; the blue link stays blue-ish.
    assert "#222222" not in out and "color:#333" not in out
    # The tinted box is a dark tint, the saturated button is untouched.
    assert "#e8f0fe" not in out
    assert "background:#1a73e8" in out and "color:#ffffff" in out
    # Light border darkened.
    assert "#e0e0e0" not in out


def test_already_dark_email_keeps_its_colors():
    html = """<style>.hero{background:#111827;color:#f9fafb}</style>
    <table width="100%" style="background-color:#000000"><tr><td class="hero" style="color:#e5e7eb">
    <h1 style="color:#ffffff">Big news</h1><p style="color:#d1d5db">Body</p>
    <p style="background:#1f2937;color:#f3f4f6">Card</p></td></tr></table>"""
    assert colors.looks_dark(fit(html, theme="").html)
    res = fit(html)
    assert res.colors == "dark"
    out = res.html.lower()
    # Its own black page becomes Kern's page; everything else as sent.
    assert "background-color:transparent" in out
    for c in ("#111827", "#f9fafb", "#e5e7eb", "#ffffff", "#d1d5db", "#1f2937", "#f3f4f6"):
        assert c in out


def test_body_bgcolor_survives_and_counts():
    html = '<html><body bgcolor="#000000" text="#eeeeee"><p>dark mail</p><p style="color:#fafafa">more</p></body></html>'
    raw = fit(html, theme="")
    assert 'style="background-color:#000000;color:#eeeeee;"' in raw.html
    assert fit(html).colors == "dark"


def test_email_with_its_own_dark_mode_is_left_alone():
    html = "<style>@media (prefers-color-scheme: dark) { .x { background:#000 } }</style><div class=x style='background:#fff'>hi</div>"
    res = fit(html)
    assert res.colors == "native"
    assert "background:#fff" in res.html


def test_light_theme_removes_only_the_white_page():
    res = fit(LIGHT_NEWSLETTER, theme="light")
    out = res.html.lower()
    assert res.colors == "light"
    assert 'bgcolor="#ffffff"' not in out and 'bgcolor="#f4f4f4"' not in out
    assert "color:#222222" in out and "#e8f0fe" in out and "#1a73e8" in out


def test_original_colors_untouched():
    res = fit(LIGHT_NEWSLETTER, theme="")
    assert res.colors == "none"
    assert 'bgcolor="#ffffff"' in res.html.lower()


def test_background_pictures_keep_their_declaration():
    out = fit('<div style="background:#fff url(cid:x) no-repeat;color:#000">x</div>').html
    assert "background:#fff" in out or "background:#ffffff" in out.lower() or "none" in out


def test_rewrite_cannot_inject_markup():
    html = '<p style="color:#000">"><script>alert(1)</script></p><div bgcolor="#fff" title="a&quot;b">x</div>'
    out = fit(html).html.lower()
    assert "<script" not in out
    assert 'title="a&quot;b"' in out


def test_style_blocks_are_adapted():
    html = "<style>p { color: #111; background-color: white } .k{border-color:#ddd}</style><p>x</p>"
    out = fit(html).html.lower()
    assert "#111;" not in out and "white" not in out and "#ddd" not in out
