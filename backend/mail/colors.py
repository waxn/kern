"""Email colors that sit on Kern's own background.

HTML mail is designed for a white page. Kern shows it without a page of its own: the email's
background becomes Kern's background, in the light and the dark theme alike, so a newsletter
doesn't arrive as a patchwork of whites, greys and blacks.

This runs on the already-sanitized HTML (mail/sanitize.py) and only ever rewrites color values
inside ``style`` attributes, ``bgcolor``/``color`` attributes and ``<style>`` blocks. It never
adds markup, so it can't weaken the sanitizer.

* Dark theme, light email: neutral near-white backgrounds become transparent (Kern's page shows
  through), other light backgrounds are darkened keeping their hue, dark text is lightened
  keeping its hue, light borders are darkened. Pictures keep their colors.
* Dark theme, email that is already dark: left as the sender made it, except that near-black
  neutral backgrounds become transparent so they match Kern's page.
* Email with its own dark-mode CSS (``prefers-color-scheme: dark``): left alone; the frame tells
  it the reader prefers dark, so the sender's own dark design applies.
* Light theme: neutral near-white backgrounds become transparent; nothing else changes.

The same result goes to the web app and the Android app, so mail looks the same on both.
"""

from __future__ import annotations

import colorsys
import re
from html.parser import HTMLParser

# CSS named colors (CSS Color 4).
_NAMED_SRC = (
    "aliceblue:f0f8ff antiquewhite:faebd7 aqua:00ffff aquamarine:7fffd4 azure:f0ffff beige:f5f5dc "
    "bisque:ffe4c4 black:000000 blanchedalmond:ffebcd blue:0000ff blueviolet:8a2be2 brown:a52a2a "
    "burlywood:deb887 cadetblue:5f9ea0 chartreuse:7fff00 chocolate:d2691e coral:ff7f50 "
    "cornflowerblue:6495ed cornsilk:fff8dc crimson:dc143c cyan:00ffff darkblue:00008b darkcyan:008b8b "
    "darkgoldenrod:b8860b darkgray:a9a9a9 darkgreen:006400 darkgrey:a9a9a9 darkkhaki:bdb76b "
    "darkmagenta:8b008b darkolivegreen:556b2f darkorange:ff8c00 darkorchid:9932cc darkred:8b0000 "
    "darksalmon:e9967a darkseagreen:8fbc8f darkslateblue:483d8b darkslategray:2f4f4f "
    "darkslategrey:2f4f4f darkturquoise:00ced1 darkviolet:9400d3 deeppink:ff1493 deepskyblue:00bfff "
    "dimgray:696969 dimgrey:696969 dodgerblue:1e90ff firebrick:b22222 floralwhite:fffaf0 "
    "forestgreen:228b22 fuchsia:ff00ff gainsboro:dcdcdc ghostwhite:f8f8ff gold:ffd700 "
    "goldenrod:daa520 gray:808080 green:008000 greenyellow:adff2f grey:808080 honeydew:f0fff0 "
    "hotpink:ff69b4 indianred:cd5c5c indigo:4b0082 ivory:fffff0 khaki:f0e68c lavender:e6e6fa "
    "lavenderblush:fff0f5 lawngreen:7cfc00 lemonchiffon:fffacd lightblue:add8e6 lightcoral:f08080 "
    "lightcyan:e0ffff lightgoldenrodyellow:fafad2 lightgray:d3d3d3 lightgreen:90ee90 lightgrey:d3d3d3 "
    "lightpink:ffb6c1 lightsalmon:ffa07a lightseagreen:20b2aa lightskyblue:87cefa "
    "lightslategray:778899 lightslategrey:778899 lightsteelblue:b0c4de lightyellow:ffffe0 lime:00ff00 "
    "limegreen:32cd32 linen:faf0e6 magenta:ff00ff maroon:800000 mediumaquamarine:66cdaa "
    "mediumblue:0000cd mediumorchid:ba55d3 mediumpurple:9370db mediumseagreen:3cb371 "
    "mediumslateblue:7b68ee mediumspringgreen:00fa9a mediumturquoise:48d1cc mediumvioletred:c71585 "
    "midnightblue:191970 mintcream:f5fffa mistyrose:ffe4e1 moccasin:ffe4b5 navajowhite:ffdead "
    "navy:000080 oldlace:fdf5e6 olive:808000 olivedrab:6b8e23 orange:ffa500 orangered:ff4500 "
    "orchid:da70d6 palegoldenrod:eee8aa palegreen:98fb98 paleturquoise:afeeee palevioletred:db7093 "
    "papayawhip:ffefd5 peachpuff:ffdab9 peru:cd853f pink:ffc0cb plum:dda0dd powderblue:b0e0e6 "
    "purple:800080 rebeccapurple:663399 red:ff0000 rosybrown:bc8f8f royalblue:4169e1 "
    "saddlebrown:8b4513 salmon:fa8072 sandybrown:f4a460 seagreen:2e8b57 seashell:fff5ee "
    "sienna:a0522d silver:c0c0c0 skyblue:87ceeb slateblue:6a5acd slategray:708090 slategrey:708090 "
    "snow:fffafa springgreen:00ff7f steelblue:4682b4 tan:d2b48c teal:008080 thistle:d8bfd8 "
    "tomato:ff6347 turquoise:40e0d0 violet:ee82ee wheat:f5deb3 white:ffffff whitesmoke:f5f5f5 "
    "yellow:ffff00 yellowgreen:9acd32"
)
NAMED = {k: v for k, v in (p.split(":") for p in _NAMED_SRC.split())}

_COLOR = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\([^()]*\)|\b(?:" + "|".join(sorted(NAMED, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
# Declarations whose colors we adapt. The property must start the declaration.
_DECL = re.compile(
    r"(?<![\w-])(?P<prop>background-color|background|color|border(?:-(?:top|right|bottom|left))?(?:-color)?|outline(?:-color)?)"
    r"\s*:\s*(?P<val>[^;{}]*)",
    re.IGNORECASE,
)
_TAG = re.compile(r"<[a-zA-Z][^\s/>]*(?:\s+[^\s=/>]+(?:=\"[^\"]*\")?)*\s*/?>")
_ATTR = re.compile(r"(?P<pre>\s)(?P<name>style|bgcolor|color)=\"(?P<val>[^\"]*)\"", re.IGNORECASE)
_STYLE_BLOCK = re.compile(r"(<style[^>]*>)(.*?)(</style>)", re.IGNORECASE | re.DOTALL)
_DARK_AWARE = re.compile(r"prefers-color-scheme\s*:\s*dark|\[data-ogsc\]|\[data-ogsb\]", re.IGNORECASE)

TRANSPARENT = "transparent"


# --- color math ------------------------------------------------------------------


def parse(token: str) -> tuple[float, float, float, float] | None:
    """A CSS color as (r, g, b, alpha), each 0..1; None for anything we don't understand."""
    t = token.strip().lower()
    if t in NAMED:
        t = "#" + NAMED[t]
    if t.startswith("#"):
        h = t[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        if len(h) not in (6, 8) or not re.fullmatch(r"[0-9a-f]+", h):
            return None
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return r, g, b, a
    m = re.fullmatch(r"(rgba?|hsla?)\((.*)\)", t)
    if not m:
        return None
    parts = [p for p in re.split(r"[\s,/]+", m.group(2).strip()) if p]
    if len(parts) < 3:
        return None

    def num(p, scale):
        try:
            return float(p[:-1]) / 100 if p.endswith("%") else float(p) / scale
        except ValueError:
            raise ValueError from None

    try:
        a = num(parts[3], 1) if len(parts) > 3 else 1.0
        if m.group(1).startswith("rgb"):
            r, g, b = (min(1.0, max(0.0, num(p, 255))) for p in parts[:3])
        else:
            hue = float(re.sub(r"deg$", "", parts[0])) / 360 % 1
            s, light = num(parts[1], 100), num(parts[2], 100)
            r, g, b = colorsys.hls_to_rgb(hue, min(1, max(0, light)), min(1, max(0, s)))
    except ValueError:
        return None
    return r, g, b, min(1.0, max(0.0, a))


def luminance(c) -> float:
    r, g, b = c[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _fmt(r: float, g: float, b: float, a: float) -> str:
    rgb = "".join(f"{round(max(0.0, min(1.0, x)) * 255):02x}" for x in (r, g, b))
    if a >= 0.999:
        return "#" + rgb
    return f"rgba({round(r * 255)},{round(g * 255)},{round(b * 255)},{a:.3g})"


def _neutral(c) -> bool:
    """White, black or grey (a page or panel color), not a tint."""
    return max(c[:3]) - min(c[:3]) < 0.06


# Each returns the new CSS color, or None to keep the original.

def bg_dark(c):
    if c[3] == 0:
        return None
    lum = luminance(c)
    if _neutral(c) and (lum > 0.9 or lum < 0.08):
        return TRANSPARENT  # white page or black page: Kern's own background
    if lum >= 0.6:
        h, light, s = colorsys.rgb_to_hls(*c[:3])
        return _fmt(*colorsys.hls_to_rgb(h, 0.1 + (1 - light) * 0.45, s * 0.55), c[3])
    return None


def fg_dark(c):
    if c[3] == 0 or luminance(c) >= 0.5:
        return None
    h, light, s = colorsys.rgb_to_hls(*c[:3])
    return _fmt(*colorsys.hls_to_rgb(h, max(0.62, 1 - light * 0.55), min(s, 0.75)), c[3])


def border_dark(c):
    if c[3] == 0 or luminance(c) < 0.6:
        return None
    h, light, s = colorsys.rgb_to_hls(*c[:3])
    return _fmt(*colorsys.hls_to_rgb(h, 0.18 + (1 - light) * 0.3, s * 0.5), c[3])


def bg_black_only(c):
    """An email that's dark already: only its black page goes."""
    return TRANSPARENT if c[3] > 0 and _neutral(c) and luminance(c) < 0.08 else None


def bg_light(c):
    return TRANSPARENT if c[3] > 0 and _neutral(c) and luminance(c) > 0.93 else None


# --- rewriting ---------------------------------------------------------------------


class _Plan:
    def __init__(self, bg=None, fg=None, border=None):
        self.bg, self.fg, self.border = bg, fg, border

    def fn(self, prop: str):
        p = prop.lower()
        if p.startswith("background"):
            return self.bg
        if p == "color":
            return self.fg
        return self.border


def _swap(value: str, fn) -> str:
    def repl(m):
        c = parse(m.group(0))
        if c is None:
            return m.group(0)
        new = fn(c)
        return new if new else m.group(0)

    return _COLOR.sub(repl, value)


def _css(css: str, plan: _Plan) -> str:
    def repl(m):
        fn = plan.fn(m.group("prop"))
        val = m.group("val")
        # A background picture keeps its whole declaration: its colors are a fallback under it.
        if fn is None or ("url(" in val.lower() and m.group("prop").lower() == "background"):
            return m.group(0)
        return m.group("prop") + ":" + _swap(val, fn)

    return _DECL.sub(repl, css)


def _rewrite(html: str, plan: _Plan) -> str:
    def attr(m):
        name, val = m.group("name").lower(), m.group("val")
        if name == "style":
            return f'{m.group("pre")}{m.group("name")}="{_css(val, plan)}"'
        fn = plan.bg if name == "bgcolor" else plan.fg
        c = parse(val) if fn else None
        new = fn(c) if c else None
        if new == TRANSPARENT:
            return ""  # bgcolor="transparent" isn't a thing: just drop it
        return f'{m.group("pre")}{m.group("name")}="{new}"' if new else m.group(0)

    def tag(m):
        return _ATTR.sub(attr, m.group(0))

    def block(m):
        return m.group(1) + _css(m.group(2), plan) + m.group(3)

    # <style> first (its contents aren't tags), then every tag's attributes outside it.
    out, last = [], 0
    for sm in _STYLE_BLOCK.finditer(html):
        out.append(_TAG.sub(tag, html[last:sm.start()]))
        out.append(block(sm))
        last = sm.end()
    out.append(_TAG.sub(tag, html[last:]))
    return "".join(out)


# --- is it dark already? -----------------------------------------------------------------


class _Scan(HTMLParser):
    """Collects painted backgrounds (with nesting depth) and explicit text colors."""

    VOID = {"br", "img", "hr", "wbr", "col", "input", "meta", "link"}

    def __init__(self, classes: dict[str, tuple]):
        super().__init__(convert_charrefs=True)
        self.classes = classes
        self.depth = 0
        self.seen = 0
        self.backgrounds: list[tuple[float, int]] = []  # (luminance, depth)
        self.texts: list[float] = []

    def handle_starttag(self, tag, attrs):
        if self.seen > 600:
            return
        self.seen += 1
        a = dict(attrs)
        bg = fg = None
        for cls in (a.get("class") or "").split():
            hit = self.classes.get(cls.lower())
            if hit:
                bg, fg = hit[0] or bg, hit[1] or fg
        if a.get("bgcolor"):
            bg = parse(a["bgcolor"]) or bg
        if tag == "font" and a.get("color"):
            fg = parse(a["color"]) or fg
        style = a.get("style") or ""
        for m in _DECL.finditer(style):
            prop = m.group("prop").lower()
            first = _COLOR.search(m.group("val"))
            c = parse(first.group(0)) if first else None
            if c and prop.startswith("background"):
                bg = c
            elif c and prop == "color":
                fg = c
        if bg and bg[3] > 0.5:
            self.backgrounds.append((luminance(bg), self.depth))
        if fg and fg[3] > 0.5:
            self.texts.append(luminance(fg))
        if tag not in self.VOID:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag not in self.VOID:
            self.depth = max(0, self.depth - 1)


_RULE = re.compile(r"([^{}@]+)\{([^{}]*)\}")


def _style_rules(html: str) -> tuple[dict[str, tuple], tuple | None, tuple | None]:
    """Colors from <style>: per simple class selector, and for the page (body/html)."""
    classes: dict[str, tuple] = {}
    page_bg = page_fg = None
    for sm in _STYLE_BLOCK.finditer(html):
        for rm in _RULE.finditer(sm.group(2)):
            bg = fg = None
            for d in _DECL.finditer(rm.group(2)):
                first = _COLOR.search(d.group("val"))
                c = parse(first.group(0)) if first else None
                if c and d.group("prop").lower().startswith("background"):
                    bg = c
                elif c and d.group("prop").lower() == "color":
                    fg = c
            if not (bg or fg):
                continue
            for sel in rm.group(1).split(","):
                sel = sel.strip().lower()
                if sel in ("body", "html", "html body", ".body", "#body", "body > table", ".wrapper", "#wrapper"):
                    page_bg, page_fg = bg or page_bg, fg or page_fg
                m = re.fullmatch(r"(?:[a-z0-9]+)?\.([\w-]+)", sel)
                if m:
                    old = classes.get(m.group(1), (None, None))
                    classes[m.group(1)] = (bg or old[0], fg or old[1])
    return classes, page_bg, page_fg


def looks_dark(html: str) -> bool:
    """Whether the email was designed light-on-dark: dark backgrounds near the outside, light text."""
    classes, page_bg, page_fg = _style_rules(html)
    scan = _Scan(classes)
    try:
        scan.feed(html[:400_000])
        scan.close()
    except Exception:  # noqa: BLE001 - a scan that fails just means "not dark"
        pass
    weight = score = 0.0
    if page_bg and page_bg[3] > 0.5:
        lum = luminance(page_bg)
        weight += 2
        score += 2 * (1 if lum < 0.35 else -1 if lum > 0.65 else 0)
    for lum, depth in scan.backgrounds[:200]:
        w = 1 / (1 + depth * 0.5)
        weight += w
        score += w * (1 if lum < 0.35 else -1 if lum > 0.65 else 0)
    texts = scan.texts + ([luminance(page_fg)] if page_fg else [])
    light = sum(1 for x in texts if x > 0.6)
    dark = sum(1 for x in texts if x < 0.4)
    text = (light - dark) / (light + dark) if light + dark else 0.0
    if not weight:
        return text > 0.5 and light >= 3
    return (score / weight) * 0.65 + text * 0.35 > 0.2


# --- the entry point ------------------------------------------------------------------


def adapt(html: str, theme: str) -> tuple[str, str]:
    """(html, how) for showing on Kern's ``theme`` ("dark" or "light").

    how: "adapted" (colors changed to fit the page), "dark" (already dark: only its black page
    removed), "native" (the email has its own dark mode), "light" (light theme: only the white
    page removed) or "none".
    """
    if theme not in ("dark", "light") or not html:
        return html, "none"
    styles = " ".join(m.group(2) for m in _STYLE_BLOCK.finditer(html))
    if _DARK_AWARE.search(styles):
        return html, "native"
    dark_email = looks_dark(html)
    if theme == "dark":
        if dark_email:
            return _rewrite(html, _Plan(bg=bg_black_only)), "dark"
        return _rewrite(html, _Plan(bg=bg_dark, fg=fg_dark, border=border_dark)), "adapted"
    if dark_email:
        return html, "dark"
    return _rewrite(html, _Plan(bg=bg_light)), "light"


_BODY = re.compile(r"<body\b([^>]*)>", re.IGNORECASE)
_BODY_BG = re.compile(r"""bgcolor\s*=\s*["']?\s*([#\w(),.%\s]+?)\s*["'\s>]""", re.IGNORECASE)
_BODY_TEXT = re.compile(r"""\btext\s*=\s*["']?\s*([#\w(),.%\s]+?)\s*["'\s>]""", re.IGNORECASE)


def body_colors(raw_html: str) -> tuple[str, str]:
    """The background and text color the email set on its <body> (which the sanitizer drops),
    as safe CSS colors ("" when unset), so they can be kept on a wrapper."""
    m = _BODY.search(raw_html[:200_000] or "")
    if not m:
        return "", ""
    attrs = m.group(1) + ">"
    bg = fg = ""
    style = re.search(r"""style\s*=\s*(["'])(.*?)\1""", attrs, re.IGNORECASE | re.DOTALL)
    for d in _DECL.finditer(style.group(2) if style else ""):
        first = _COLOR.search(d.group("val"))
        c = parse(first.group(0)) if first else None
        if c and d.group("prop").lower().startswith("background"):
            bg = _fmt(*c)
        elif c and d.group("prop").lower() == "color":
            fg = _fmt(*c)
    if not bg and (b := _BODY_BG.search(attrs)) and (c := parse(b.group(1))):
        bg = _fmt(*c)
    if not fg and (t := _BODY_TEXT.search(attrs)) and (c := parse(t.group(1))):
        fg = _fmt(*c)
    return bg, fg
