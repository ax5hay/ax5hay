#!/usr/bin/env python3
"""Render the profile README's plates as animated SVG, in a light and a dark issue.

Every image in the README is drawn here from data/*.json, in the site's own
type (Instrument Serif, IBM Plex Mono, IBM Plex Sans), embedded so GitHub's
image proxy shows it the same everywhere. Motion is CSS and SMIL inside the
SVG: no scripts, no GIFs, no third-party cards. Every animated element rests
in its final state, so `prefers-reduced-motion` shows a finished drawing.

    python scripts/render.py                    # re-issue every plate
    GITHUB_TOKEN=... python scripts/render.py   # also refresh data/stats.json

Standard library only, plus fontTools when installed: it cuts each embedded
font down to the glyphs that plate draws. Without it the full latin subsets
are embedded and everything still renders.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import math
import os
import random
import subprocess
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
DATA = ROOT / "data"
W = 1200           # every plate shares one width; GitHub scales it to the column
M = 34             # sheet field margin
FIRST_ISSUE = "2026-10-10"

# --------------------------------------------------------------------------
# Issue states: the site's "artifact" (paper) and "annotated" (night
# blueprint) modes, token for token, plus the colours of fire and x-ray.
# --------------------------------------------------------------------------
THEMES = {
    "light": dict(
        board="#ded2b8", sheet="#fcfaf4", raised="#ffffff", sunk="#f1ece0", deep="#f4efe3",
        ink="#141417", ink2="#413c34", ink3="#5c5548", ink4="#6f6655",
        rule_faint="rgba(20,20,23,0.12)", rule="rgba(20,20,23,0.28)",
        rule_strong="rgba(20,20,23,0.62)", rule_ink="rgba(20,20,23,0.9)",
        grid_minor="rgba(20,20,23,0.055)", grid_major="rgba(20,20,23,0.11)",
        accent="#983729", accent_soft="rgba(152,55,41,0.12)",
        accent_line="rgba(152,55,41,0.55)", accent2="#2f5d8c", accent2_soft="rgba(47,93,140,0.12)",
        fire_outer="#c4532f", fire_mid="#e0873a", fire_core="#f6cf73", diamond="#2f5d8c",
        glow_op=0.35, smoke="#c9bfa9", ok="#2f7d4a", phosphor="#983729", scope="#f1ece0",
        vignette="rgba(120,96,60,0.10)", lens_fill="#fcfaf4",
    ),
    "dark": dict(
        board="#03111f", sheet="#082139", raised="#0c2b49", sunk="#041322", deep="#020c17",
        ink="#e6f1fc", ink2="#9dbdd9", ink3="#7b9ebf", ink4="#6a8dab",
        rule_faint="rgba(157,207,255,0.12)", rule="rgba(157,207,255,0.28)",
        rule_strong="rgba(198,227,255,0.62)", rule_ink="rgba(230,241,252,0.92)",
        grid_minor="rgba(140,195,255,0.075)", grid_major="rgba(140,195,255,0.15)",
        accent="#ffc75a", accent_soft="rgba(255,199,90,0.14)",
        accent_line="rgba(255,199,90,0.7)", accent2="#6fe3a0", accent2_soft="rgba(111,227,160,0.14)",
        fire_outer="#ff6a2b", fire_mid="#ffb347", fire_core="#fff4d8", diamond="#bdf0ff",
        glow_op=1.0, smoke="#9dbdd9", ok="#4fd68a", phosphor="#ffc75a", scope="#020c17",
        vignette="rgba(0,6,14,0.55)", lens_fill="#061a2e",
    ),
}

FONT_FILES = {
    "serif": ("InstrumentSerif-Regular.woff2", "normal"),
    "serif-i": ("InstrumentSerif-Italic.woff2", "italic"),
    "mono": ("IBMPlexMono-Regular.woff2", "normal"),
    "mono-m": ("IBMPlexMono-Medium.woff2", "normal"),
    "sans": ("IBMPlexSans-Regular.woff2", "normal"),
}
MONO_ADVANCE = 0.6   # IBM Plex Mono: 600/1000 em per glyph
# Instrument Serif advances (em), read from the embedded font. Digits are
# proportional, so odometer drums use the widest one for every column.
SERIF_ADV = {",": 0.217, ".": 0.213, "+": 0.531, "%": 0.59, "<": 0.531, "M": 0.665, "K": 0.496, " ": 0.17}
SERIF_DIGIT = 0.47
SANS_ADVANCE = 0.52  # IBM Plex Sans, average lower-case advance

# Motion shared by every plate. Each animation runs *from* a hidden or
# starting state *to* the element's resting state, so with motion off the
# drawing is simply complete.
BASE_CSS = (
    "text{white-space:pre}"
    # unique family names: a face called "serif" would lose to the generic keyword
    ".serif{font-family:'ax-serif','Instrument Serif',Georgia,serif}"
    ".serif-i{font-family:'ax-serif-i','Instrument Serif',Georgia,serif;font-style:italic}"
    ".mono{font-family:'ax-mono','IBM Plex Mono',ui-monospace,Menlo,monospace}"
    ".mono-m{font-family:'ax-mono-m','IBM Plex Mono',ui-monospace,Menlo,monospace}"
    ".sans{font-family:'ax-sans','IBM Plex Sans',system-ui,sans-serif}"
    ".dr{stroke-dasharray:1 1;animation:dr 1.6s cubic-bezier(.65,0,.25,1) backwards}"
    "@keyframes dr{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}"
    ".fi{animation:fi 1s ease-out backwards}"
    "@keyframes fi{from{opacity:0}}"
    ".up{animation:up 1s cubic-bezier(.2,.7,.2,1) backwards}"
    "@keyframes up{from{opacity:0;transform:translateY(16px)}}"
    ".lt{animation:lt 1s cubic-bezier(.2,.7,.2,1) backwards}"
    "@keyframes lt{from{opacity:0;transform:translateX(-14px)}}"
    ".fb{transform-box:fill-box}"
)
REDUCED = "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"


_SUBSET_CACHE: dict = {}


def _font_b64(key: str, chars: str | None) -> str:
    """The font as base64 woff2, cut down to `chars` when fontTools is around.

    Subsetting keeps each plate to the glyphs it draws (a card drops from about
    80 kB to about 25 kB). Without fontTools the whole latin subset is embedded,
    which still renders the same.
    """
    name, _ = FONT_FILES[key]
    raw = (ASSETS / "fonts" / name).read_bytes()
    if chars is None:
        return base64.b64encode(raw).decode()
    ck = (key, chars)
    if ck in _SUBSET_CACHE:
        return _SUBSET_CACHE[ck]
    try:
        import io
        from fontTools import subset
        from fontTools.ttLib import TTFont
        f = TTFont(io.BytesIO(raw))
        opts = subset.Options()
        opts.flavor = "woff2"
        opts.layout_features = ["kern", "liga", "tnum", "lnum"]
        opts.name_IDs = []
        opts.notdef_outline = True
        sub = subset.Subsetter(opts)
        sub.populate(text=chars)
        sub.subset(f)
        buf = io.BytesIO()
        f.flavor = "woff2"
        f.save(buf)
        out = base64.b64encode(buf.getvalue()).decode()
    except Exception:
        out = base64.b64encode(raw).decode()
    _SUBSET_CACHE[ck] = out
    return out


def font_faces(*keys: str, chars: str | None = None) -> str:
    out = []
    for k in keys:
        _, style = FONT_FILES[k]
        out.append(
            f'@font-face{{font-family:"ax-{k}";font-style:{style};font-weight:400;'
            f'src:url(data:font/woff2;base64,{_font_b64(k, chars)}) format("woff2");}}'
        )
    return "".join(out)


def mono_w(s: str, size: float, tracking: float = 0.0) -> float:
    return len(s) * size * (MONO_ADVANCE + tracking)


def _used_chars(body: str) -> str:
    """Every character the plate draws as text, plus digits and spacing."""
    import html
    import re
    drawn = "".join(re.sub(r"<[^>]+>", "", m) for m in re.findall(r"<text[^>]*>(.*?)</text>", body, re.S))
    return "".join(sorted(set(html.unescape(drawn)) | set("0123456789 .,:+-%")))


def svg(width, height, body, fonts, title, css="") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="t">\n'
        f'<title id="t">{escape(title)}</title>\n'
        f"<style>{font_faces(*fonts, chars=_used_chars(body))}{BASE_CSS}{css}{REDUCED}</style>\n"
        f"{body}\n</svg>\n"
    )


def d_(delay: float, dur: float | None = None) -> str:
    """Inline animation timing."""
    s = f"animation-delay:{delay:.2f}s"
    if dur is not None:
        s += f";animation-duration:{dur:.2f}s"
    return f' style="{s}"'


def drum(x, y0, step, glyphs, cls, size, fill):
    """A column of glyphs as one text element: one paint item instead of one per glyph."""
    spans = "".join(f'<tspan x="{x:.1f}" y="{y0 + i * step:.1f}">{escape(g)}</tspan>' for i, g in enumerate(glyphs))
    return f'<text class="{cls}" font-size="{size}" fill="{fill}" text-anchor="middle">{spans}</text>'


def text(x, y, s, cls, size, fill, anchor="start", tracking=None, extra=""):
    ls = f' letter-spacing="{tracking}em"' if tracking else ""
    # an animated label passes its own class list (font class first) in `extra`
    c = "" if 'class="' in extra else f' class="{cls}"'
    return (
        f'<text x="{x:.1f}" y="{y:.1f}"{c} font-size="{size}" fill="{fill}" '
        f'text-anchor="{anchor}"{ls}{extra}>{escape(s)}</text>'
    )


def label(x, y, s, t, fill=None, size=12, anchor="start", extra=""):
    """A drafting label: small uppercase mono, tracked wide."""
    return text(x, y, s.upper(), "mono-m", size, fill or t["ink4"], anchor, tracking=0.16, extra=extra)


def rule(x1, y1, x2, y2, stroke, w=1.0, dash="", extra=""):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{stroke}" stroke-width="{w}"{d}{extra}/>'
    )


def pen(d, stroke, w=1.0, delay=0.0, dur=1.6, fill="none", extra=""):
    """A path the plotter draws in."""
    return (f'<path d="{d}" pathLength="1" class="dr" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{w}"{d_(delay, dur)}{extra}/>')


def line_pen(x1, y1, x2, y2, stroke, w=1.0, delay=0.0, dur=0.9):
    return pen(f"M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}", stroke, w, delay, dur)


def wrap(s: str, size: float, width: float, adv=SANS_ADVANCE) -> list[str]:
    words, lines, cur = s.split(), [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if len(trial) * size * adv > width and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def grid_defs(t, idp="g", minor=24, major=120):
    return (
        f'<pattern id="{idp}" width="{minor}" height="{minor}" patternUnits="userSpaceOnUse">'
        f'<path d="M{minor} 0H0V{minor}" fill="none" stroke="{t["grid_minor"]}" stroke-width="0.6"/></pattern>'
        f'<pattern id="{idp}M" width="{major}" height="{major}" patternUnits="userSpaceOnUse">'
        f'<rect width="{major}" height="{major}" fill="url(#{idp})"/>'
        f'<path d="M{major} 0H0V{major}" fill="none" stroke="{t["grid_major"]}" stroke-width="0.8"/></pattern>'
    )


def vignette_defs(t, idp="vig"):
    return (f'<radialGradient id="{idp}" cx="50%" cy="45%" r="75%">'
            f'<stop offset="0.55" stop-color="{t["vignette"]}" stop-opacity="0"/>'
            f'<stop offset="1" stop-color="{t["vignette"]}"/></radialGradient>')


def sheet_frame(t, H, field_bottom, cols="ABCDEFGHJK", grid=True):
    """The board, the sheet, its margin, and the grid references on the edge."""
    o = [f'<defs>{grid_defs(t)}{vignette_defs(t)}</defs>',
         f'<rect width="{W}" height="{H}" fill="{t["board"]}"/>',
         f'<rect x="14" y="14" width="{W-28}" height="{H-28}" rx="3" fill="{t["sheet"]}" stroke="{t["rule_strong"]}" stroke-width="1"/>']
    if grid:
        o.append(f'<rect x="{M}" y="{M}" width="{W-2*M}" height="{field_bottom-M}" fill="url(#gM)"/>')
    o.append(f'<rect x="14" y="14" width="{W-28}" height="{H-28}" rx="3" fill="url(#vig)"/>')
    o.append(f'<rect x="{M}" y="{M}" width="{W-2*M}" height="{H-2*M}" fill="none" stroke="{t["rule"]}" stroke-width="0.8"/>')
    for i, c in enumerate(cols):
        x = M + (W - 2 * M) * (i + 0.5) / len(cols)
        o.append(text(x, 28, c, "mono", 10, t["ink4"], "middle"))
        o.append(text(x, H - 18, c, "mono", 10, t["ink4"], "middle"))
        if i:
            xx = M + (W - 2 * M) * i / len(cols)
            o.append(rule(xx, 14, xx, 21, t["rule"], 0.8))
            o.append(rule(xx, H - 21, xx, H - 14, t["rule"], 0.8))
    rows = max(2, round((H - 2 * M) / 150))
    for i in range(rows):
        y = M + (H - 2 * M) * (i + 0.5) / rows
        o.append(text(24, y + 3.5, str(i + 1), "mono", 10, t["ink4"], "middle"))
        o.append(text(W - 24, y + 3.5, str(i + 1), "mono", 10, t["ink4"], "middle"))
        if i:
            yy = M + (H - 2 * M) * i / rows
            o.append(rule(14, yy, 21, yy, t["rule"], 0.8))
            o.append(rule(W - 21, yy, W - 14, yy, t["rule"], 0.8))
    return o


def title_block(t, y, cells, h=62):
    """The drawing's title block: label over value, cells separated by rules."""
    o = [rule(M, y, W - M, y, t["rule_strong"], 1.2), rule(M, y + 3, W - M, y + 3, t["rule_faint"], 0.8)]
    x = M
    for i, (lab, val, w) in enumerate(cells):
        if i:
            o.append(rule(x, y + 3, x, y + h, t["rule"], 0.8))
        o.append(label(x + 14, y + 24, lab, t, t["ink4"], 10.5))
        o.append(text(x + 14, y + 48, val, "mono-m", 15, t["ink"]))
        x += w
    return o


def stamp(x, y, head, body, t, angle=-7, delay=2.8):
    """The inspector's stamp, in the sheet's one hot colour. It lands."""
    w, h = 200, 68
    return (
        f'<g transform="translate({x},{y}) rotate({angle})">'
        f'<g class="stamp"{d_(delay)}>'
        f'<rect x="{-w/2}" y="{-h/2}" width="{w}" height="{h}" rx="4" fill="{t["sheet"]}" fill-opacity="0.8" stroke="{t["accent"]}" stroke-width="2"/>'
        f'<rect x="{-w/2+5}" y="{-h/2+5}" width="{w-10}" height="{h-10}" rx="2" fill="none" stroke="{t["accent"]}" stroke-width="0.8"/>'
        + text(0, -h / 2 + 24, head.upper(), "mono-m", 11, t["accent"], "middle", tracking=0.22)
        + text(0, h / 2 - 13, body, "mono-m", 20, t["accent"], "middle", tracking=0.06)
        + "</g></g>"
    )


STAMP_CSS = (".stamp{animation:stamp .5s cubic-bezier(.3,1.6,.5,1) backwards}"
             "@keyframes stamp{0%{opacity:0;transform:scale(2.2)}60%{opacity:1}100%{transform:scale(1)}}")


# --------------------------------------------------------------------------
# Odometers: a column of digits behind a window, rolled to the value.
# --------------------------------------------------------------------------
class Odo:
    """Collects the keyframes a plate's odometers need."""

    def __init__(self):
        self.frames: dict[str, str] = {}
        self.n = 0

    def number(self, x, y, s, size, fill, cls="serif", delay=0.0, dur=2.2, anchor="start"):
        """Draw `s` with its digits on rolling drums. Returns (svg, width)."""
        L = round(size * 1.15, 1)
        if cls.startswith("serif"):
            widths = [size * (SERIF_DIGIT if ch.isdigit() else SERIF_ADV.get(ch, 0.5)) for ch in s]
        else:
            widths = [size * MONO_ADVANCE for ch in s]
        total = sum(widths)
        x0 = x - total if anchor == "end" else x - total / 2 if anchor == "middle" else x
        self.n += 1
        cid = f"odc{self.n}"
        o = [f'<clipPath id="{cid}"><rect x="{x0-4:.1f}" y="{y-size*0.86:.1f}" width="{total+8:.1f}" height="{size*1.08:.1f}"/></clipPath>',
             f'<g clip-path="url(#{cid})">']
        cx = x0
        digit_i = 0
        for ch, w in zip(s, widths):
            if ch.isdigit():
                d = int(ch)
                spins = 10 + d   # one full turn, then the digit
                k = f"od{int(L*10)}_{spins}"
                self.frames[k] = f"@keyframes {k}{{from{{transform:translateY({spins*L:.1f}px)}}}}"
                stack = drum(cx + w / 2, y, L, [str(i % 10) for i in range(spins + 1)], cls, size, fill)
                o.append(f'<g transform="translate(0,{-spins*L:.1f})"><g style="animation:{k} {dur+digit_i*0.25:.2f}s '
                         f'cubic-bezier(.2,.75,.25,1) {delay:.2f}s backwards">{stack}</g></g>')
                digit_i += 1
            else:
                o.append(text(cx + w / 2, y, ch, cls, size, fill, "middle"))
            cx += w
        o.append("</g>")
        return "".join(o), total

    def clock(self, x, y, size, fill, delay=0.0, cls="mono-m"):
        """A mission clock, T+ hh:mm:ss, that starts when the sheet is opened."""
        L = round(size * 1.2, 1)
        cw = size * 0.6
        cols = [("0", None), ("0", None), (":", None), ("m10", (6, 3600)), ("m1", (10, 600)),
                (":", None), ("s10", (6, 60)), ("s1", (10, 10))]
        self.n += 1
        cid = f"clk{self.n}"
        total = cw * len(cols)
        o = [f'<clipPath id="{cid}"><rect x="{x-2:.1f}" y="{y-size*0.85:.1f}" width="{total+4:.1f}" height="{size*1.1:.1f}"/></clipPath>',
             f'<g clip-path="url(#{cid})">']
        cx = x
        for key, roll in cols:
            if roll is None:
                o.append(text(cx + cw / 2, y, key, cls, size, fill, "middle"))
            else:
                n, period = roll
                k = f"tick{n}_{int(L*10)}"
                self.frames[k] = f"@keyframes {k}{{to{{transform:translateY({-n*L:.1f}px)}}}}"
                stack = drum(cx + cw / 2, y, L, [str(i) for i in range(n)], cls, size, fill)
                o.append(f'<g style="animation:{k} {period}s steps({n}) {delay:.2f}s infinite">{stack}</g>')
            cx += cw
        o.append("</g>")
        return "".join(o)

    def css(self):
        return "".join(self.frames.values())


# --------------------------------------------------------------------------
# Plate 1: the title sheet. A thrust chamber drawn by a plotter, then lit.
# --------------------------------------------------------------------------
def engine_lines(t, delay0=0.6):
    """The engine as a drafting detail, in local units (throat on the axis)."""
    ink, strong, faint = t["rule_ink"], t["rule_strong"], t["rule"]
    o = []
    dome_y, cham_top, cham_bot, throat_y, exit_y = 40, 62, 142, 184, 300
    rc, rt, re_ = 40, 15, 84

    def wall(s, off=0.0):
        return (f"M{s*(rc-off)},{cham_top} V{cham_bot} "
                f"Q{s*(rc-off)},{throat_y-10} {s*(rt+off*0.4)},{throat_y} "
                f"Q{s*(rc-4-off)},{throat_y+70} {s*(re_-off*1.2)},{exit_y}")

    dl = delay0
    o.append(f'<path d="M0,4 V340" stroke="{faint}" stroke-width="0.6" stroke-dasharray="14 4 2 4" class="fi"{d_(dl)}/>')
    # gimbal mount: the control surface itself
    o.append(pen(f"M-26,{dome_y-2} L-34,16 H34 L26,{dome_y-2}", ink, 1.1, dl + 0.1, 1.0))
    o.append(f'<circle cx="0" cy="16" r="5" fill="{t["sheet"]}" stroke="{ink}" stroke-width="1.1" class="fi"{d_(dl+0.5)}/>')
    o.append(f'<circle cx="0" cy="16" r="1.4" fill="{ink}" class="fi"{d_(dl+0.5)}/>')
    for s in (-1, 1):
        o.append(pen(f"M{s*48},10 L{s*34},16 L{s*48},22 Z", strong, 0.7, dl + 0.4, 0.8))
    # injector dome and plate
    o.append(pen(f"M{-rc},{cham_top} Q0,{dome_y-30} {rc},{cham_top}", ink, 1.4, dl + 0.3, 1.0))
    o.append(pen(f"M{-rc+6},{cham_top} Q0,{dome_y-16} {rc-6},{cham_top}", faint, 0.6, dl + 0.5, 1.0))
    o.append(pen(f"M{-rc},{cham_top} H{rc}", ink, 1.4, dl + 0.6, 0.6))
    for i in range(-3, 4):
        o.append(f'<circle cx="{i*10.5}" cy="{cham_top+6}" r="1.6" fill="none" stroke="{strong}" stroke-width="0.6" class="fi"{d_(dl+0.9+abs(i)*0.05)}/>')
    # walls, outer and inner: the cooling jacket lives between them
    for s in (-1, 1):
        o.append(pen(wall(s), ink, 1.5, dl + 0.7, 1.8))
        o.append(pen(wall(s, 7), strong, 0.6, dl + 0.95, 1.8))
    for i in range(7):
        y = cham_top + 10 + i * 10
        o.append(line_pen(-rc, y + 4, -rc + 7, y - 2, strong, 0.55, dl + 1.4 + i * 0.05, 0.3))
        o.append(line_pen(rc - 7, y + 4, rc, y - 2, strong, 0.55, dl + 1.4 + i * 0.05, 0.3))
    for i in range(1, 7):
        f = i / 7
        y = throat_y + (exit_y - throat_y) * f
        r = rt + (re_ - rt) * (f ** 0.72)
        o.append(line_pen(-r + 1, y, -r + 7, y - 3, faint, 0.55, dl + 1.9 + i * 0.05, 0.3))
        o.append(line_pen(r - 7, y - 3, r - 1, y, faint, 0.55, dl + 1.9 + i * 0.05, 0.3))
    for i in range(1, 4):
        f = i / 4
        y = throat_y + (exit_y - throat_y) * f
        r = (rt + (re_ - rt) * (f ** 0.72)) - 9
        o.append(pen(f"M{-r},{y} Q0,{y+14} {r},{y}", t["rule_faint"], 0.7, dl + 2.0 + i * 0.1, 0.6))
    o.append(f'<path d="M{-re_-10},{exit_y} H{re_+10}" stroke="{faint}" stroke-width="0.6" stroke-dasharray="3 3" class="fi"{d_(dl+2.2)}/>')
    # the throat: the one dimension that decides everything
    o.append(line_pen(-rt - 40, throat_y, -rt - 2, throat_y, faint, 0.6, dl + 2.0, 0.5))
    o.append(text(-rt - 44, throat_y + 3, "throat", "mono", 8, t["ink4"], "end", extra=f' class="mono fi"{d_(dl+2.2)}'))
    return "\n".join(o)


def engine_fire(t, ign: float):
    """Plume, Mach diamonds, sparks and shock rings, in local units."""
    o = []
    ex = 300
    g = t["glow_op"]
    o.append(
        '<defs>'
        f'<linearGradient id="fo" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t["fire_outer"]}" stop-opacity="{0.55*g+0.15:.2f}"/>'
        f'<stop offset="0.6" stop-color="{t["fire_outer"]}" stop-opacity="{0.18*g+0.05:.2f}"/><stop offset="1" stop-color="{t["fire_outer"]}" stop-opacity="0"/></linearGradient>'
        f'<linearGradient id="fm" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t["fire_mid"]}" stop-opacity="0.95"/>'
        f'<stop offset="0.7" stop-color="{t["fire_mid"]}" stop-opacity="0.35"/><stop offset="1" stop-color="{t["fire_mid"]}" stop-opacity="0"/></linearGradient>'
        f'<linearGradient id="fc" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t["fire_core"]}"/>'
        f'<stop offset="0.75" stop-color="{t["fire_core"]}" stop-opacity="0.7"/><stop offset="1" stop-color="{t["fire_core"]}" stop-opacity="0"/></linearGradient>'
        + "".join(
            f'<linearGradient id="h{k}" x1="0" x2="1"><stop offset="0" stop-color="{c}" stop-opacity="0"/>'
            f'<stop offset=".5" stop-color="{c}" stop-opacity="{op:.2f}"/><stop offset="1" stop-color="{c}" stop-opacity="0"/></linearGradient>'
            for k, c, op in (("o", t["fire_outer"], 0.75 * g + 0.15), ("m", t["fire_mid"], 0.95), ("c", t["fire_core"], 1.0)))
        + f'<linearGradient id="pfade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff"/>'
        f'<stop offset=".45" stop-color="#fff" stop-opacity=".75"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
        f'<mask id="pm" maskUnits="userSpaceOnUse" maskContentUnits="userSpaceOnUse" x="-200" y="{ex-4}" width="400" height="420">'
        f'<rect x="-200" y="{ex-4}" width="400" height="400" fill="url(#pfade)"/></mask>'
        f'<radialGradient id="fd"><stop offset="0" stop-color="#ffffff" stop-opacity="{0.95 if g > .5 else 0.0}"/>'
        f'<stop offset="0.35" stop-color="{t["diamond"]}" stop-opacity="0.9"/><stop offset="1" stop-color="{t["diamond"]}" stop-opacity="0"/></radialGradient>'
        f'<radialGradient id="fg"><stop offset="0" stop-color="{t["fire_mid"]}" stop-opacity="{0.55*g:.2f}"/>'
        f'<stop offset="1" stop-color="{t["fire_outer"]}" stop-opacity="0"/></radialGradient>'
        f'<radialGradient id="cg"><stop offset="0" stop-color="{t["fire_core"]}" stop-opacity="{0.9 if g > .5 else 0.55}"/>'
        f'<stop offset="0.5" stop-color="{t["fire_mid"]}" stop-opacity="{0.45 if g > .5 else 0.25}"/><stop offset="1" stop-color="{t["fire_outer"]}" stop-opacity="0"/></radialGradient>'
        '</defs>'
    )
    o.append(f'<g class="ign"{d_(ign)}>')
    # a wide bloom of heat under everything
    if g > .5:
        o.append(f'<ellipse cx="0" cy="{ex+120}" rx="190" ry="210" fill="url(#fg)" class="fb pulse"/>')
    # shock rings rolling off the exit plane
    for i in range(3):
        o.append(f'<ellipse cx="0" cy="{ex+6}" rx="86" ry="22" fill="none" stroke="{t["fire_mid"]}" stroke-width="0.9" '
                 f'class="fb ring" style="animation-delay:{ign+0.4+i*1.2:.2f}s"/>')
    o.append('<g mask="url(#pm)">')
    o.append(f'<path class="fb fl1" d="M-96,{ex} C-118,{ex+90} -84,{ex+250} 0,{ex+390} C84,{ex+250} 118,{ex+90} 96,{ex} Z" fill="url(#ho)"/>')
    o.append(f'<path class="fb fl2" d="M-72,{ex} C-80,{ex+70} -46,{ex+200} 0,{ex+310} C46,{ex+200} 80,{ex+70} 72,{ex} Z" fill="url(#hm)"/>')
    o.append(f'<path class="fb fl3" d="M-50,{ex} C-52,{ex+40} -24,{ex+130} 0,{ex+210} C24,{ex+130} 52,{ex+40} 50,{ex} Z" fill="url(#hc)"/>')
    o.append('</g>')
    o.append(f'<ellipse cx="0" cy="{ex+2}" rx="78" ry="3.5" fill="{t["fire_core"]}" fill-opacity="{0.7 if g > .5 else 0.4}" class="fb pulse"/>')
    # Mach diamonds: standing shocks, brightest nearest the throat
    for i, (dy, w, h) in enumerate([(30, 30, 22), (78, 24, 20), (122, 18, 17), (160, 12, 14)]):
        o.append(f'<ellipse cx="0" cy="{ex+dy}" rx="{w+14}" ry="{h+6}" fill="url(#fd)" class="fb dia" style="animation-delay:{-i*0.17:.2f}s"/>')
        o.append(f'<path d="M0,{ex+dy-h} L{w},{ex+dy} L0,{ex+dy+h} L{-w},{ex+dy} Z" fill="none" stroke="{t["diamond"]}" '
                 f'stroke-width="0.8" stroke-opacity="0.8" class="fb dia" style="animation-delay:{-i*0.17:.2f}s"/>')
    # sparks shed into the plume
    rnd = random.Random(7)
    for i in range(22):
        x = rnd.uniform(-46, 46)
        dur = rnd.uniform(1.0, 2.1)
        r = rnd.uniform(0.6, 1.6)
        o.append(f'<circle cx="{x:.1f}" cy="{ex+8}" r="{r:.1f}" fill="{t["fire_core"] if g > .5 else t["fire_outer"]}" class="spark" '
                 f'style="animation-duration:{dur:.2f}s;animation-delay:{-rnd.uniform(0, 2):.2f}s;--dx:{x*rnd.uniform(0.2,0.7):.1f}px"/>')
    o.append("</g>")
    return "\n".join(o)


def engine_glow(t, ign: float):
    """Light inside the chamber and the throat: drawn under the walls."""
    return (f'<g class="ign"{d_(ign-0.15)}>'
            f'<ellipse cx="0" cy="104" rx="36" ry="46" fill="url(#cg)" class="fb pulse"/>'
            f'<ellipse cx="0" cy="186" rx="22" ry="16" fill="url(#cg)" class="fb pulse" style="animation-delay:-.3s"/>'
            f'<path d="M-62,268 Q0,330 62,268 L80,300 H-80 Z" fill="url(#cg)" opacity=".5" class="fb pulse" style="animation-delay:-.6s"/>'
            "</g>")


FIRE_CSS = (
    ".ign{animation:ign 1.1s cubic-bezier(.2,.9,.2,1) backwards}"
    "@keyframes ign{0%{opacity:0}30%{opacity:1}}"
    ".fl1,.fl2,.fl3{transform-origin:50% 0}"
    ".fl1{animation:fl 0.31s ease-in-out infinite alternate}"
    ".fl2{animation:fl 0.23s ease-in-out infinite alternate-reverse}"
    ".fl3{animation:fl 0.17s ease-in-out infinite alternate}"
    "@keyframes fl{from{transform:scale(1,1)}to{transform:scale(.965,1.07)}}"
    ".dia{transform-origin:50% 50%;animation:dia .52s ease-in-out infinite alternate}"
    "@keyframes dia{from{opacity:1;transform:scale(1)}to{opacity:.55;transform:scale(.88,1.08)}}"
    ".pulse{transform-origin:50% 50%;animation:pulse 1.7s ease-in-out infinite alternate}"
    "@keyframes pulse{from{opacity:1}to{opacity:.6;transform:scale(.94)}}"
    ".spark{animation:spark 1.6s linear infinite}"
    "@keyframes spark{0%{opacity:0;transform:translate(0,0)}10%{opacity:1}100%{opacity:0;transform:translate(var(--dx),240px)}}"
    ".ring{transform-origin:50% 50%;animation:ring 3.6s cubic-bezier(.1,.6,.3,1) infinite backwards}"
    "@keyframes ring{0%{opacity:0;transform:scale(.7)}15%{opacity:.45}100%{opacity:0;transform:scale(1.7,2.1)}}"
)


def xray_layer(t):
    """The software inside the engine, visible only through the lens."""
    c = t["accent2"]
    o = []

    def box(x, y, w, h, s):
        o.append(f'<rect x="{x-w/2}" y="{y-h/2}" width="{w}" height="{h}" rx="2" fill="{t["accent2_soft"]}" stroke="{c}" stroke-width="0.7"/>')
        o.append(text(x, y + 2.6, s, "mono-m", 7.2, c, "middle"))

    # the bus down the axis, with data flowing along it
    o.append(f'<path d="M0,20 V300" stroke="{c}" stroke-width="0.8" stroke-opacity=".5"/>')
    o.append(f'<path d="M0,20 V300" stroke="{c}" stroke-width="1.6" stroke-dasharray="2 9" class="flow"/>')
    for y, x1, x2 in [(80, -22, 22), (110, -22, 22), (230, -24, 24), (262, -40, 40)]:
        o.append(f'<path d="M{x1},{y} H{x2}" stroke="{c}" stroke-width="0.6" stroke-opacity=".6"/>')
    box(0, 30, 56, 13, "orchestrator")
    box(-16, 80, 34, 12, "queue")
    box(18, 80, 30, 12, "lease")
    box(0, 110, 52, 12, "schema")
    box(0, 134, 52, 12, "contracts")
    o.append(f'<path d="M0,176 L12,186 L0,196 L-12,186 Z" fill="{t["accent2_soft"]}" stroke="{c}" stroke-width="0.8"/>')
    o.append(text(22, 189, "guard", "mono-m", 7.2, c))
    box(0, 216, 40, 12, "evals")
    box(-26, 240, 34, 12, "retry")
    box(26, 240, 34, 12, "trace")
    box(-40, 268, 34, 12, "audit")
    box(0, 268, 30, 12, "cost")
    box(40, 268, 38, 12, "runbook")
    for x in (-54, -18, 18, 54):
        o.append(f'<circle cx="{x}" cy="292" r="1.6" fill="{c}"/>')
    return "\n".join(o)


LENS_PATH = ("M0,70 C46,82 58,150 34,204 C14,252 64,262 26,282 C-14,300 -60,262 -34,212 "
             "C-10,168 -54,120 -36,92 C-26,76 -14,66 0,70 Z")


def plate_hero(t, stats, updated, rev, n_materials) -> str:
    H = 852
    TBY = H - M - 66
    odo = Odo()
    o = sheet_frame(t, H, TBY)

    # the plotter carriage crosses the sheet once, laying the drawing down
    o.append(f'<g class="carriage"><path d="M0,{M} V{TBY}" stroke="{t["accent"]}" stroke-width="1" stroke-opacity=".7"/>'
             f'<rect x="-7" y="{M-2}" width="14" height="10" fill="{t["accent"]}"/>'
             f'<rect x="-5" y="{TBY-8}" width="10" height="8" fill="{t["accent"]}"/></g>')

    # ---- left field: the name and the thesis
    o.append(label(70, 112, "Sheet GH-01  ·  GitHub profile", t, t["accent"], 13, extra=f' class="mono-m lt"{d_(0.2)}'))
    # the name is inked the way a pen would: outlines first, then the fill floods in
    o.append(text(62, 214, "Akshay Bajpai", "serif", 122, t["ink"],
                  extra=f' class="serif ink" stroke="{t["ink"]}" stroke-width="0.9" style="--L:900;animation-delay:.35s"'))
    o.append(text(68, 278, "In thrust we trust.", "serif-i", 50, t["accent"],
                  extra=f' class="serif-i ink" stroke="{t["accent"]}" stroke-width="0.6" style="--L:420;animation-delay:1.1s;animation-duration:1.8s"'))
    o.append(line_pen(70, 314, 230, 314, t["rule_strong"], 1, 0.9, 0.8))
    stand = ["I lead technology from the first client",
             "conversation to the release: the architecture,",
             "the team, the code, and the runbook after.",
             "Built to hold under load and fail loud."]
    for i, s in enumerate(stand):
        o.append(f'<g class="up"{d_(0.95+i*0.1)}>' + text(70, 356 + i * 31, s, "sans", 21, t["ink2"]) + "</g>")
    o.append(label(70, 512, "Boardroom to bare metal", t, t["accent"], 13.5, extra=f' class="mono-m lt"{d_(1.5)}'))
    o.append(label(70, 540, "Clients · teams · architecture · AI · code", t, t["ink3"], 12, extra=f' class="mono-m lt"{d_(1.6)}'))

    # live counts, rolled up on drums
    counts = [(f'{stats["repos_total"]}', "repositories"),
              (f'{stats["contributions_last_year"]:,}', "contributions, 12 mo"),
              (f"{n_materials}", "materials in use")]
    x = 70
    o.append(line_pen(70, 578, 610, 578, t["rule"], 0.8, 1.7, 0.9))
    for i, (v, lab) in enumerate(counts):
        s, wv = odo.number(x, 630, v, 40, t["ink"], "serif", 1.8 + i * 0.15, 2.0)
        o.append(s)
        o.append(label(x, 656, lab, t, t["ink4"], 10.5, extra=f' class="mono-m fi"{d_(2.0+i*0.15)}'))
        x += max(wv, mono_w(lab, 10.5, 0.16)) + 44

    # ---- right field: the engine, drawn, then lit
    cx, top, s = 870, 66, 1.34
    ign = 2.9
    loc = f"translate({cx},{top}) scale({s})"
    o.append(f'<defs><clipPath id="plume"><rect x="{M}" y="{M}" width="{W-2*M}" height="{TBY-M}"/></clipPath>'
             f'<mask id="lensM" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{H}">'
             f'<g transform="{loc}"><circle r="44" fill="#fff"><animateMotion dur="19s" begin="{ign+0.8}s" repeatCount="indefinite" path="{LENS_PATH}"/></circle></g>'
             f'</mask></defs>')
    # thrust vectoring: the engine swings a degree or so about its gimbal, plume and all
    pvx, pvy = cx, top + 16 * s
    gimbal = (f'<animateTransform attributeName="transform" type="rotate" dur="9s" begin="{ign+1.2}s" repeatCount="indefinite" '
              f'calcMode="spline" keyTimes="0;0.3;0.65;1" keySplines=".45 0 .55 1;.45 0 .55 1;.45 0 .55 1" '
              f'values="0 {pvx} {pvy:.1f};1.3 {pvx} {pvy:.1f};-1.1 {pvx} {pvy:.1f};0 {pvx} {pvy:.1f}"/>')
    # actuators: the bodies hang from the mount, the rods ride on the chamber
    act_body, act_rod = [], []
    for sgn in (-1, 1):
        ax_, ay_ = cx + sgn * 58 * s, top + 16 * s
        bx_, by_ = cx + sgn * 40 * s, top + 96 * s
        mxp, myp = ax_ + (bx_ - ax_) * 0.55, ay_ + (by_ - ay_) * 0.55
        act_body.append(f'<path d="M{ax_:.1f},{ay_:.1f} L{mxp:.1f},{myp:.1f}" stroke="{t["rule_ink"]}" stroke-width="5.5" stroke-linecap="round" class="fi"{d_(1.6)}/>'
                        f'<path d="M{ax_:.1f},{ay_:.1f} L{mxp:.1f},{myp:.1f}" stroke="{t["sheet"]}" stroke-width="3" stroke-linecap="round" class="fi"{d_(1.6)}/>'
                        f'<circle cx="{ax_:.1f}" cy="{ay_:.1f}" r="3" fill="{t["sheet"]}" stroke="{t["rule_ink"]}" stroke-width="1" class="fi"{d_(1.6)}/>')
        rx2, ry2 = ax_ + (bx_ - ax_) * 0.35, ay_ + (by_ - ay_) * 0.35
        act_rod.append(f'<path d="M{bx_:.1f},{by_:.1f} L{rx2:.1f},{ry2:.1f}" stroke="{t["rule_strong"]}" stroke-width="1.6" class="fi"{d_(1.6)}/>'
                       f'<circle cx="{bx_:.1f}" cy="{by_:.1f}" r="2.6" fill="{t["sheet"]}" stroke="{t["rule_ink"]}" stroke-width="1" class="fi"{d_(1.6)}/>')
    o.append(f'<g clip-path="url(#plume)"><g>{gimbal}<g transform="{loc}">{engine_fire(t, ign)}</g></g></g>')
    o.append(f'<g>{gimbal}{"".join(act_rod)}<g transform="{loc}">{engine_glow(t, ign)}{engine_lines(t)}</g></g>')
    o.append("".join(act_body))
    # the lens: what the engine is really made of
    o.append(f'<g mask="url(#lensM)"><g class="fi"{d_(ign+0.8)}><g transform="{loc}">'
             f'<rect x="-120" y="0" width="240" height="320" fill="{t["lens_fill"]}" fill-opacity=".94"/>'
             f'<rect x="-120" y="0" width="240" height="320" fill="url(#gM)"/>'
             f'{xray_layer(t)}</g></g></g>')
    ticks = "".join(
        f'<line x1="{46*math.cos(a):.1f}" y1="{46*math.sin(a):.1f}" x2="{(50 if k % 3 == 0 else 48)*math.cos(a):.1f}" '
        f'y2="{(50 if k % 3 == 0 else 48)*math.sin(a):.1f}" stroke="{t["accent2"]}" stroke-width="0.6"/>'
        for k in range(36) for a in [k * math.pi / 18])
    o.append(f'<g class="fi"{d_(ign+0.8)}><g transform="{loc}"><g>'
             f'<animateMotion dur="19s" begin="{ign+0.8}s" repeatCount="indefinite" path="{LENS_PATH}"/>'
             f'<circle r="44" fill="none" stroke="{t["accent2"]}" stroke-width="1.3"/>'
             f'<g class="spin">{ticks}</g>'
             f'<path d="M-56,0 H-48 M48,0 H56 M0,-56 V-48 M0,48 V56" stroke="{t["accent2"]}" stroke-width="0.8"/>'
             + text(0, -58, "X-RAY  ·  L", "mono-m", 6.5, t["accent2"], "middle", tracking=0.2) +
             "</g></g></g>")

    # an overall dimension, gimbal to exit plane, and a section cut through the chamber
    dx_ = cx - 150
    y1d, y2d = top + 16 * s, top + 300 * s
    for yy, x_from in ((y1d, cx - 52 * s), (y2d, cx - 90 * s)):
        o.append(line_pen(x_from, yy, dx_ - 8, yy, t["rule"], 0.8, 2.5, 0.5))
    o.append(line_pen(dx_, y1d, dx_, y2d, t["rule_strong"], 0.9, 2.7, 0.9))
    for yy, sg in ((y1d, 1), (y2d, -1)):
        o.append(f'<path d="M{dx_},{yy:.1f} l-3.5,{sg*10} h7 Z" fill="{t["rule_strong"]}" class="fi"{d_(3.2)}/>')
    ym = (y1d + y2d) / 2
    o.append(f'<g class="fi"{d_(3.3)}><rect x="{dx_-8}" y="{ym-62:.1f}" width="16" height="124" fill="{t["sheet"]}"/>'
             + text(dx_ + 4, ym, "gimbal to exit plane", "mono", 10.5, t["ink3"], "middle", extra=f' class="mono" transform="rotate(-90 {dx_+4} {ym:.1f})"')
             + "</g>")
    sy_ = top + 112 * s
    o.append(f'<path d="M{cx-92},{sy_:.1f} H{cx+92}" stroke="{t["rule_strong"]}" stroke-width="0.8" stroke-dasharray="16 4 3 4" class="fi"{d_(3.0)}/>')
    for sg in (-1, 1):
        ex_ = cx + sg * 92
        o.append(f'<g class="fi"{d_(3.1)}><path d="M{ex_-sg*12},{sy_:.1f} H{ex_}" stroke="{t["rule_ink"]}" stroke-width="2.4"/>'
                 f'<path d="M{ex_-sg*6},{sy_-2:.1f} V{sy_-16:.1f}" stroke="{t["rule_ink"]}" stroke-width="1.2"/>'
                 f'<path d="M{ex_-sg*6-4},{sy_-12:.1f} L{ex_-sg*6},{sy_-20:.1f} L{ex_-sg*6+4},{sy_-12:.1f} Z" fill="{t["rule_ink"]}"/>'
                 f'<circle cx="{ex_+sg*12}" cy="{sy_:.1f}" r="8" fill="{t["sheet"]}" stroke="{t["rule_ink"]}" stroke-width="1"/>'
                 + text(ex_ + sg * 12, sy_ + 3.6, "A", "mono-m", 10, t["ink"], "middle") + "</g>")

    # callouts: leaders from the parts to the right margin, drawn after the walls
    def G(px, py):
        return cx + px * s, top + py * s
    lx = cx + 150
    callouts = [((26, 13), "orchestration", top + 14),
                ((28, 68), "schema that refuses", top + 80),
                ((15, 184), "safety and guardrails", top + 236),
                ((66, 248), "observability", top + 330)]
    for i, ((px, py), lab, ly) in enumerate(callouts):
        gx, gy = G(px, py)
        dl = 2.4 + i * 0.12
        o.append(f'<circle cx="{gx:.1f}" cy="{gy:.1f}" r="2.6" fill="{t["accent"]}" class="fi"{d_(dl)}/>')
        o.append(pen(f"M{gx:.1f},{gy:.1f} L{lx-14:.1f},{ly:.1f} H{lx-5:.1f}", t["accent_line"], 1, dl, 0.7))
        o.append(text(lx, ly + 4.5, lab, "mono", 13.5, t["ink2"], extra=f' class="mono fi"{d_(dl+0.4)}'))
        if lab == "schema that refuses":
            o.append(text(lx, ly + 23, "bad data", "mono", 13.5, t["ink2"], extra=f' class="mono fi"{d_(dl+0.4)}'))
    gx, gy = G(66, 248)
    o.append(f'<circle cx="{gx:.1f}" cy="{gy:.1f}" r="5" fill="none" stroke="{t["rule_ink"]}" stroke-width="1" class="fi"{d_(2.7)}/>')

    # hot-fire readout: the clock starts at ignition
    rx, ry = cx - 266, top + 330 * s + 6
    o.append(label(rx, ry, "hot fire", t, t["accent"], 11.5, extra=f' class="mono-m fi"{d_(ign)}'))
    o.append(f'<g class="fi"{d_(ign)}>' + text(rx, ry + 28, "T+", "mono-m", 19, t["ink3"]) +
             odo.clock(rx + 30, ry + 28, 19, t["ink"], ign) + "</g>")
    o.append(f'<g class="up"{d_(ign+0.6)}>' + text(rx, ry + 70, "Controlled,", "serif-i", 30, t["accent"]) +
             text(rx, ry + 102, "it is trust.", "serif-i", 30, t["accent"]) + "</g>")

    # ---- title block
    o += title_block(t, TBY, [
        ("drawn by", "ax5hay", 150), ("title", "Boardroom to bare metal", 300), ("sheet", "GH-01 of 01", 170),
        ("scale", "NTS", 110), ("first issued", FIRST_ISSUE, 190), ("rev", str(rev), W - 2 * M - 920)])
    o.append(stamp(W - 170, TBY - 118, "last updated", updated, t, -6, 3.3))

    # ---- the set, as a strip of sheet tags: what is below this one
    sheets = [("GH-01", "this sheet"), ("GN", "General notes"), ("RW", "Record of work"), ("KP", "Key plan"),
              ("SI", "Sheet index"), ("SM", "Schedule"), ("TM", "Telemetry"), ("END", "End of set")]
    sy0 = TBY - 54
    o.append(label(70, sy0 - 14, "in this set", t, t["ink4"], 10.5, extra=f' class="mono-m fi"{d_(3.4)}'))
    tw_ = (W - 70 - 70 - 7 * 8) / len(sheets)
    for k, (code, ttl) in enumerate(sheets):
        x_ = 70 + k * (tw_ + 8)
        here = k == 0
        o.append(f'<g transform="translate({x_+tw_/2:.1f},{sy0+17})"><g class="tagin" style="animation-delay:{3.5+k*0.09:.2f}s">'
                 f'<rect x="{-tw_/2:.1f}" y="-17" width="{tw_:.1f}" height="34" rx="3" fill="{t["accent"] if here else t["sheet"]}" '
                 f'fill-opacity="{1 if here else 0.85}" stroke="{t["accent"] if here else t["rule_strong"]}" stroke-width="1"/>'
                 + text(-tw_ / 2 + 10, 4.5, code, "mono-m", 11.5, t["sheet"] if here else t["accent"])
                 + text(tw_ / 2 - 9, 4.5, ttl, "mono", 9.8, t["sheet"] if here else t["ink2"], "end")
                 + "</g></g>")
        if k:
            o.append(f'<path d="M{x_-7:.1f},{sy0+17} h6" stroke="{t["rule"]}" stroke-width="1" class="fi"{d_(3.6)}/>')
    o.append(f'<path d="M{70+tw_/2:.1f},{sy0+38} l-5,8 h10 Z" fill="{t["accent"]}" class="here"/>')

    css = (odo.css() + FIRE_CSS + STAMP_CSS +
           ".carriage{animation:carriage 2.6s cubic-bezier(.45,0,.35,1) .1s backwards}"
           f"@keyframes carriage{{0%{{transform:translateX({M}px);opacity:1}}92%{{opacity:1}}100%{{transform:translateX({W-M}px);opacity:0}}}}"
           ".carriage{opacity:0}"
           ".tagin{animation:tagin .55s cubic-bezier(.3,1.6,.5,1) backwards}@keyframes tagin{from{opacity:0;transform:scale(.6)}}"
           ".here{animation:here 1.6s ease-in-out infinite alternate}@keyframes here{to{transform:translateY(3px);opacity:.5}}"
           ".ink{stroke-dasharray:var(--L);animation:ink 2.6s cubic-bezier(.5,0,.3,1) backwards}"
           "@keyframes ink{0%{stroke-dashoffset:var(--L);fill-opacity:0}62%{stroke-dashoffset:0;fill-opacity:0}100%{stroke-dashoffset:0;fill-opacity:1}}"
           ".spin{animation:spin 24s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}"
           ".flow{animation:flow 1.2s linear infinite}@keyframes flow{to{stroke-dashoffset:-11}}")
    alt = ("Akshay Bajpai. In thrust we trust. I lead technology from the first client conversation to the release: "
           "the architecture, the team, the code, and the runbook after. Boardroom to bare metal. "
           "The name is inked, outlines first. A rocket engine is drawn by a plotter, dimensioned and cut at section A-A, then lit; "
           "it vectors on its gimbal while an x-ray lens drifts over it and shows the software inside. "
           "A strip lists the sheets in the set.")
    return svg(W, H, "\n".join(o), ("serif", "serif-i", "mono", "mono-m", "sans"), alt, css)


# --------------------------------------------------------------------------
# Plate 1b: general notes. Seven notes, each with a figure that does what the
# note says, and the sheet's approval block in the eighth cell.
# --------------------------------------------------------------------------
def note_figure(t, k, x0, y0, w, h):
    acc, ink, faint, strong = t["accent"], t["rule_ink"], t["rule"], t["rule_strong"]
    o = [f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" rx="4" fill="{t["deep"]}" stroke="{strong}" stroke-width="0.9"/>']
    cx, cy = x0 + w / 2, y0 + h / 2
    if k == 0:
        # thrust, controlled: one vector thrashes, the gimballed one holds
        for bx, cls, col, lab in ((x0 + w * 0.28, "wild", strong, "thrust"), (x0 + w * 0.72, "held", acc, "trust")):
            by = y0 + h - 26
            L_ = min(h - 60, 110)
            o.append(f'<g transform="translate({bx:.1f},{by})"><g class="{cls}">'
                     f'<path d="M0,0 V{-L_}" stroke="{col}" stroke-width="2.6"/><path d="M-7,{-L_+9} L0,{-L_-4} L7,{-L_+9}" fill="none" stroke="{col}" stroke-width="2.6"/></g>'
                     f'<circle r="6" fill="{t["sheet"]}" stroke="{ink}" stroke-width="1.2"/></g>')
            o.append(text(bx, y0 + h - 8, lab, "mono-m", 10, t["ink3"] if cls == "wild" else acc, "middle"))
        o.append(f'<path d="M{x0+w*0.72-18:.1f},{y0+h-26} a18,18 0 0 1 36,0" fill="none" stroke="{acc}" stroke-width="0.9" stroke-dasharray="2 3"/>')
    elif k == 1:
        # one seat that moves between the boardroom side and the bare-metal side
        tx, ty, tw, th = x0 + 30, cy - 16, w - 60, 32
        o.append(f'<rect x="{tx}" y="{ty}" width="{tw}" height="{th}" rx="4" fill="{t["raised"]}" stroke="{ink}" stroke-width="1.1"/>')
        for i in range(3):
            sx = tx + tw * (i + 0.5) / 3
            for sy in (ty - 14, ty + th + 14):
                o.append(f'<rect x="{sx-9:.1f}" y="{sy-6}" width="18" height="12" rx="3" fill="none" stroke="{faint}" stroke-width="1"/>')
        o.append(text(cx, y0 + 16, "boardroom", "mono-m", 9.5, t["ink3"], "middle"))
        o.append(text(cx, y0 + h - 8, "bare metal", "mono-m", 9.5, t["ink3"], "middle"))
        route = f"M{cx:.1f},{ty-14} H{tx+tw+14} V{ty+th+14} H{cx:.1f} H{tx-14} V{ty-14} H{cx:.1f}"
        o.append(f'<g><animateMotion dur="8s" repeatCount="indefinite" path="{route}" keyPoints="0;0;0.5;0.5;1" keyTimes="0;0.3;0.5;0.8;1" calcMode="linear"/>'
                 f'<circle r="9" fill="{acc}" fill-opacity=".2"/><circle r="5" fill="{acc}"/></g>')
    elif k == 2:
        # one pair of hands, every stage
        stages = ["drawing", "product", "safety", "release", "runbook"]
        sy0, step = y0 + 20, (h - 36) / 4
        o.append(f'<path d="M{x0+24},{sy0} V{sy0+4*step}" stroke="{faint}" stroke-width="1.2"/>')
        for i, s in enumerate(stages):
            yy = sy0 + i * step
            o.append(f'<circle cx="{x0+24}" cy="{yy:.1f}" r="5.5" fill="{t["sheet"]}" stroke="{ink}" stroke-width="1.1"/>')
            o.append(f'<circle cx="{x0+24}" cy="{yy:.1f}" r="3" fill="{acc}" class="stg" style="animation-delay:{i*0.8:.1f}s"/>')
            o.append(text(x0 + 40, yy + 4, s, "mono", 11, t["ink2"]))
        o.append(f'<g><animateMotion dur="4s" repeatCount="indefinite" path="M{x0+24},{sy0} V{sy0+4*step}"/>'
                 f'<circle r="9" fill="{acc}" fill-opacity=".25"/></g>')
    elif k == 3:
        # the job queue that survives a restart
        ly = cy + 4
        o.append(f'<path d="M{x0+10},{ly} H{x0+w-10}" stroke="{faint}" stroke-width="1"/>')
        bx = x0 + w * 0.5 - 24
        o.append(f'<rect x="{bx:.1f}" y="{ly-22}" width="48" height="44" rx="4" fill="{t["raised"]}" stroke="{ink}" stroke-width="1.1"/>')
        o.append(f'<rect x="{bx:.1f}" y="{ly-22}" width="48" height="44" rx="4" fill="#e5484d" class="crash"/>')
        o.append(text(bx + 24, ly - 28, "worker", "mono-m", 9.5, t["ink3"], "middle"))
        o.append(text(bx + 24, ly + 38, "lease", "mono", 9.5, t["ink4"], "middle"))
        for i in range(4):
            o.append(f'<rect x="{x0+6}" y="{ly-6}" width="16" height="12" rx="2" fill="{acc}" class="job" style="animation-delay:{-i*1.5:.1f}s"/>')
        o.append(text(x0 + w - 8, y0 + 16, "restart", "mono-m", 9, "#e5484d", "end", extra=' class="mono-m crashT"'))
    elif k == 4:
        # the decision record writes itself, then it is accepted
        px, py, pw, ph = x0 + 26, y0 + 12, w - 52, h - 24
        o.append(f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" fill="{t["sheet"]}" stroke="{ink}" stroke-width="1.1"/>')
        o.append(text(px + 8, py + 16, "ADR-0007", "mono-m", 10, acc))
        widths = (0.9, 0.75, 0.85, 0.6, 0.8, 0.5, 0.88, 0.7, 0.4, 0.82, 0.66, 0.9, 0.55, 0.78)
        n_ = int((ph - 70) // 12)
        for i, f in enumerate(widths[:n_]):
            o.append(f'<rect x="{px+8}" y="{py+28+i*12+(8 if i > 3 else 0)+(8 if i > 8 else 0)}" width="{(pw-16)*f:.1f}" height="4" fill="{faint}" '
                     f'class="wr" style="animation-delay:{i*0.3:.2f}s"/>')
        o.append(f'<g transform="translate({px+pw-30},{py+ph-22}) rotate(-12)"><g class="acc">'
                 f'<rect x="-30" y="-10" width="60" height="20" rx="2" fill="none" stroke="{acc}" stroke-width="1.6"/>'
                 + text(0, 4, "ACCEPTED", "mono-m", 8.5, acc, "middle") + "</g></g>")
    elif k == 5:
        # a figure, and the conditions it was measured under
        oy = y0 + (h - 150) / 2
        o.append(text(x0 + 16, oy + 56, "94%", "serif", 48, t["ink"]))
        o.append(text(x0 + 92, oy + 30, "1", "mono-m", 11, acc))
        o.append(pen(f"M{x0+98},{oy+36} C{x0+118},{oy+66} {x0+66},{oy+76} {x0+66},{oy+92}", acc, 1, 0.6, 1.0))
        rows = ["precision", "held-out set", "results file"]
        for i, r in enumerate(rows):
            yy = oy + 106 + i * 17
            o.append(f'<g class="row" style="animation-delay:{1.2+i*0.3:.1f}s">' + rule(x0 + 14, yy + 4, x0 + w - 14, yy + 4, faint, 0.7)
                     + text(x0 + 16, yy, f"{i+1 if i == 0 else ' '} {r}" if i == 0 else f"  {r}", "mono", 9.5, t["ink2"]) + "</g>")
    else:
        # a router: most questions never need a model
        rx, ry = x0 + 46, cy
        o.append(f'<path d="M{rx},{ry-12} L{rx+12},{ry} L{rx},{ry+12} L{rx-12},{ry} Z" fill="{t["raised"]}" stroke="{ink}" stroke-width="1.1"/>')
        exits = [("saved answer", y0 + 26, faint), ("plain rule", cy, faint), ("model", y0 + h - 26, acc)]
        for lab, ey, col in exits:
            o.append(f'<path d="M{rx+12},{ry} C{rx+40},{ry} {rx+40},{ey} {rx+60},{ey} H{x0+w-10}" fill="none" stroke="{col}" stroke-width="1"/>')
            o.append(text(x0 + w - 10, ey - 5, lab, "mono", 9.5, t["ink3"] if col == faint else acc, "end"))
        o.append(f'<path d="M{x0+8},{ry} H{rx-12}" stroke="{faint}" stroke-width="1"/>')
        plan = [0, 1, 0, 0, 1, 2]  # one in six reaches the model
        for i, e in enumerate(plan):
            ey = exits[e][1]
            pth = f"M{x0+8},{ry} H{rx+12} C{rx+40},{ry} {rx+40},{ey} {rx+60},{ey} H{x0+w-10}"
            o.append(f'<circle r="3.2" fill="{acc if e == 2 else t["ink2"]}" opacity="0"><animateMotion dur="6s" begin="{i:.0f}s" repeatCount="indefinite" '
                     f'path="{pth}" keyPoints="0;1;1" keyTimes="0;0.4;1" calcMode="linear"/>'
                     f'<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;0.38;0.4;1" dur="6s" begin="{i:.0f}s" repeatCount="indefinite"/></circle>')
    return "".join(o)


NOTE_CSS = (
    ".wild{animation:wild 1.9s ease-in-out infinite}"
    "@keyframes wild{0%{transform:rotate(-24deg)}18%{transform:rotate(19deg)}31%{transform:rotate(-8deg)}47%{transform:rotate(28deg)}63%{transform:rotate(-30deg)}80%{transform:rotate(12deg)}100%{transform:rotate(-24deg)}}"
    ".held{animation:held 2.4s ease-in-out infinite alternate}@keyframes held{from{transform:rotate(-2.5deg)}to{transform:rotate(2.5deg)}}"
    ".stg{opacity:.15;animation:stg 4s linear infinite}@keyframes stg{0%,8%{opacity:1}30%,100%{opacity:.15}}"
    ".job{animation:job 6s linear infinite}"
    "@keyframes job{0%{transform:translateX(0);opacity:0}5%{opacity:1}40%{transform:translateX(52px)}55%{transform:translateX(52px)}95%{opacity:1}100%{transform:translateX(118px);opacity:0}}"
    ".crash{opacity:0;animation:crash 6s steps(1) infinite}@keyframes crash{0%{opacity:0}42%{opacity:.55}50%{opacity:0}}"
    ".crashT{opacity:0;animation:crash 6s steps(1) infinite}"
    ".wr{transform-box:fill-box;transform-origin:0 0;animation:wr 7s ease-out infinite backwards}"
    "@keyframes wr{0%{transform:scaleX(0)}8%,100%{transform:scaleX(1)}}"
    ".acc{opacity:0;animation:acc 7s cubic-bezier(.3,1.6,.5,1) infinite}"
    "@keyframes acc{0%,44%{opacity:0;transform:scale(2)}50%,92%{opacity:1;transform:scale(1)}100%{opacity:0}}"
    ".row{animation:fi .6s ease-out backwards}"
    "@media (prefers-reduced-motion:reduce){.acc{opacity:1}.stg{opacity:1}}"
)


def plate_notes(t, notes, updated, rev) -> str:
    COLS, GX, GY = 2, 22, 20
    X0, Y0 = 52, 58
    PW = (W - 2 * X0 - GX) / COLS
    FW = 184
    TW = PW - FW - 74
    # every panel is as tall as the tallest note needs
    lay = []
    for n in notes:
        tl = wrap(n["title"], 25, TW, 0.43)
        bl = wrap(n["body"], 15.5, TW, 0.535)
        lay.append((tl, bl))
    need = max(36 + len(tl) * 29 + 14 + len(bl) * 22 for tl, bl in lay)
    PH = max(214, need + 22)
    FH = PH - 22
    rows = (len(notes) + 1 + COLS - 1) // COLS
    H = Y0 + rows * PH + (rows - 1) * GY + 52
    o = sheet_frame(t, H, H - M, cols="ABCDEFGH")
    o.append(label(X0, 44, f"General notes  ·  {len(notes)} notes  ·  read before the drawings", t, t["accent"], 12, extra=f' class="mono-m lt"{d_(0.1)}'))
    for i, (n, (tl, bl)) in enumerate(zip(notes, lay)):
        col, row = i % COLS, i // COLS
        px, py = X0 + col * (PW + GX), Y0 + row * (PH + GY)
        dl = 0.15 + i * 0.12
        o.append(f'<g class="up"{d_(dl)}>')
        o.append(f'<rect x="{px:.1f}" y="{py}" width="{PW:.1f}" height="{PH}" rx="6" fill="{t["sheet"]}" fill-opacity=".85" stroke="{t["rule_strong"]}" stroke-width="1"/>')
        o.append(f'<circle cx="{px+30:.1f}" cy="{py+34}" r="17" fill="{t["accent"]}"/>')
        o.append(text(px + 30, py + 42, str(i + 1), "serif", 25, t["sheet"], "middle"))
        for k, ln in enumerate(tl):
            o.append(text(px + 60, py + 42 + k * 29, ln, "serif", 25, t["ink"]))
        by = py + 42 + len(tl) * 29 + 6
        for k, ln in enumerate(bl):
            o.append(text(px + 60, by + k * 22, ln, "sans", 15.5, t["ink2"]))
        fx, fy = px + PW - FW - 16, py + 18
        o.append(note_figure(t, i, fx, fy, FW, FH - 26))
        o.append(text(fx + FW, fy + FH - 8, f"fig. {i+1}  ·  {n['fig']}", "mono", 10.5, t["ink4"], "end"))
        o.append("</g>")
    # the eighth cell: the approval block
    i = len(notes)
    col, row = i % COLS, i // COLS
    px, py = X0 + col * (PW + GX), Y0 + row * (PH + GY)
    o.append(f'<g class="up"{d_(0.15+i*0.12)}>')
    o.append(f'<rect x="{px:.1f}" y="{py}" width="{PW:.1f}" height="{PH}" rx="6" fill="none" stroke="{t["rule_strong"]}" stroke-width="1" stroke-dasharray="5 4"/>')
    o.append(text(px + 28, py + 52, "Read before the drawings.", "serif-i", 30, t["accent"]))
    fields = [("drawn", "ax5hay"), ("checked", "ax5hay"), ("issued", updated), ("revision", str(rev))]
    for k, (a, b) in enumerate(fields):
        yy = py + 92 + k * 28
        o.append(label(px + 30, yy, a, t, t["ink4"], 11))
        o.append(text(px + 150, yy, b, "mono-m", 14, t["ink"]))
        o.append(rule(px + 30, yy + 9, px + 330, yy + 9, t["rule_faint"], 0.8))
    o.append("</g>")
    o.append(stamp(px + PW - 118, py + PH / 2 + 6, "issued for", "construction", t, -8, 2.2).replace("font-size=\"20\"", "font-size=\"17\""))
    alt = "General notes. " + " ".join(f"{k+1}. {n['title']} {n['body']}" for k, n in enumerate(notes))
    return svg(W, H, "\n".join(o), ("serif", "serif-i", "mono", "mono-m", "sans"), alt, NOTE_CSS + STAMP_CSS)


def notes_markdown(notes) -> str:
    def pic(path, alt):
        return (f'<picture>\n  <source media="(prefers-color-scheme: dark)" srcset="assets/dark/{path}">\n'
                f'  <img src="assets/light/{path}" width="100%" alt="{escape(alt, {chr(34): "&quot;"})}">\n</picture>')
    alt = "General notes, each with a working figure. " + " ".join(f"{k+1}. {n['title']} {n['body']}" for k, n in enumerate(notes))
    lines = "\n".join(f"{k+1}. **{n['title']}** {n['body']}" for k, n in enumerate(notes))
    return ("\n" + pic("notes.svg", alt) + "\n\n<details>\n<summary>The same notes as text</summary>\n<br>\n\n"
            + lines + "\n\n</details>\n")


# --------------------------------------------------------------------------
# Section headers: a discipline code, the title, a double rule, a note
# --------------------------------------------------------------------------
def plate_header(t, code: str, title: str, note: str = "", seq: str = "") -> str:
    H = 92
    o = [
        f'<g class="wipe"><rect x="0" y="28" width="44" height="32" fill="{t["accent"]}"/>'
        + text(22, 49.5, code, "mono-m", 14, t["sheet"], "middle", tracking=0.08) + "</g>",
        f'<g class="lt"{d_(0.2)}>' + text(62, 57, title, "serif", 46, t["ink"]) + "</g>",
        line_pen(0, 76, W, 76, t["rule_strong"], 1.6, 0.1, 1.4),
        line_pen(0, 81, W, 81, t["rule"], 0.7, 0.3, 1.4),
        f'<circle cx="{W-4}" cy="76" r="3.5" fill="{t["accent"]}" class="fi"{d_(1.4)}/>',
    ]
    if note:
        o.append(f'<g class="fi"{d_(0.7)}>' + text(W, 56, note, "serif-i", 24, t["ink3"], "end") + "</g>")
    if seq:
        o.append(label(W, 22, seq, t, t["ink4"], 11, "end"))
    css = ".wipe{animation:wipe .6s cubic-bezier(.2,.8,.2,1) backwards;transform-origin:0 0}@keyframes wipe{from{transform:scaleX(0)}}"
    return svg(W, H, "\n".join(o), ("serif", "serif-i", "mono-m"), title, css)


# --------------------------------------------------------------------------
# Plate 2: the test stand. The record of work, read off its instruments.
# --------------------------------------------------------------------------
GAUGES = [
    # kind of work, value shown, fraction of the dial, dial ends, reading, conditions
    ("Defence video intelligence", "70%", 0.70, ("0", "100%"), "less analyst intervention", "under 200 ms, ingestion to decision"),
    ("Multi-tenant health AI", "8,000+", 0.80, ("0", "10K"), "approved columns, reportable", "193 tables · 100+ prompts retired"),
    ("Restaurant operations", "32%", 0.32, ("0", "100%"), "less food waste", "validated across 200+ restaurants"),
    ("Event pipelines", "2M+", 0.667, ("0", "3M"), "events a day", "each one under 100 ms"),
    ("Agentic finance", "60%", 0.60, ("0", "100%"), "fewer manual touchpoints", "risk, rebalancing, onboarding"),
    ("Fine-tuned health models", "80%", 0.80, ("0", "100%"), "lower inference cost", "94% precision · p95 under 800 ms"),
    ("Insurance documents", "95%+", 0.95, ("0", "100%"), "extraction accuracy", "underwriting efficiency up 78%"),
    ("Clinical NLP", "91.5%", 0.915, ("0", "100%"), "accuracy on 47+ variables", "5K+ health records a day"),
]


def test_rig(t, EY, GY):
    """A horizontal engine on a thrust stand, firing into a deflector; taps along it."""
    ink, strong, faint = t["rule_ink"], t["rule_strong"], t["rule"]
    o = []

    def r_at(x):
        if x <= 500:
            return 34
        if x <= 560:
            f = (x - 500) / 60
            return 34 - 20 * f ** 1.6
        return 14 + 50 * ((x - 560) / 140) ** 0.8
    # ground, deflector, stand
    o.append(f'<rect x="{M+22}" y="{GY}" width="{W-2*M-44}" height="12" fill="url(#gM)"/>')
    o.append(rule(M + 22, GY, W - M - 22, GY, t["rule_strong"], 1.2))
    for k in range(56):
        xx = M + 30 + k * 20
        o.append(rule(xx, GY, xx - 8, GY + 9, faint, 0.7))
    o.append(f'<path d="M1050,{GY} V{EY-96} H1072 V{GY}" fill="url(#gM)" stroke="{ink}" stroke-width="1.2"/>')
    for k in range(10):
        o.append(rule(1050, EY - 90 + k * 18, 1072, EY - 78 + k * 18, faint, 0.7))
    for lx in (390, 610):
        o.append(f'<path d="M{lx-34},{GY} L{lx},{EY+r_at(lx)+4} L{lx+34},{GY}" fill="none" stroke="{strong}" stroke-width="1.4"/>')
        o.append(f'<path d="M{lx-24},{GY-24} H{lx+24}" stroke="{faint}" stroke-width="0.9"/>')
    # thrust takeout to the load cell
    o.append(f'<path d="M270,{EY} H322" stroke="{ink}" stroke-width="2"/>')
    o.append(f'<rect x="236" y="{EY-20}" width="34" height="40" rx="3" fill="{t["raised"]}" stroke="{ink}" stroke-width="1.2"/>')
    o.append(f'<path d="M226,{EY-40} V{GY}" stroke="{ink}" stroke-width="3"/>')
    o.append(label(236, EY - 30, "load cell", t, t["ink3"], 10))
    # the plume, into the deflector
    o.append(f'<g class="hfire"><path d="M700,{EY-60} C780,{EY-70} 900,{EY-40} 1048,{EY-14} V{EY+14} C900,{EY+40} 780,{EY+70} 700,{EY+60} Z" fill="url(#hp1)" class="fb hfl1"/>'
             f'<path d="M700,{EY-34} C760,{EY-36} 840,{EY-18} 930,{EY} C840,{EY+18} 760,{EY+36} 700,{EY+34} Z" fill="url(#hp2)" class="fb hfl2"/>')
    for k, (dx, w, h) in enumerate([(30, 22, 26), (82, 18, 20), (128, 14, 15)]):
        o.append(f'<path d="M{700+dx-w},{EY} L{700+dx},{EY-h} L{700+dx+w},{EY} L{700+dx},{EY+h} Z" fill="url(#hd)" class="fb hdia" style="animation-delay:{-k*0.15:.2f}s"/>')
    o.append("</g>")
    # engine outline
    o.append(f'<path d="M340,{EY-34} Q304,{EY} 340,{EY+34}" fill="{t["sheet"]}" stroke="{ink}" stroke-width="1.4"/>')
    top = f"M340,{EY-34} H500 Q540,{EY-34} 560,{EY-14} Q600,{EY-22} 700,{EY-64}"
    bot = f"M340,{EY+34} H500 Q540,{EY+34} 560,{EY+14} Q600,{EY+22} 700,{EY+64}"
    o.append(f'<path d="{top} L700,{EY+64} Q600,{EY+22} 560,{EY+14} Q540,{EY+34} 500,{EY+34} H340 Z" fill="{t["sheet"]}" fill-opacity=".9"/>')
    o.append(f'<path d="{top}" fill="none" stroke="{ink}" stroke-width="1.5"/><path d="{bot}" fill="none" stroke="{ink}" stroke-width="1.5"/>')
    o.append(f'<path d="M700,{EY-64} V{EY+64}" stroke="{faint}" stroke-width="0.8" stroke-dasharray="3 3"/>')
    o.append(f'<path d="M300,{EY} H1040" stroke="{faint}" stroke-width="0.6" stroke-dasharray="14 4 2 4"/>')
    for k in range(6):
        o.append(rule(350 + k * 26, EY - 34, 360 + k * 26, EY - 26, strong, 0.7))
    o.append(label(M + 22, EY - 92, "thrust stand  ·  eight channels, one per engagement", t, t["ink3"], 11))
    o.append(label(1061, EY - 104, "deflector", t, t["ink4"], 10, "middle"))
    taps = [370, 420, 470, 520, 560, 612, 656, 692]
    return o, [(x, EY + r_at(x)) for x in taps]


def plate_teststand(t) -> str:
    COLS, CW = 4, (W - 2 * M) / 4
    ROW_H = 372
    RIG = 268
    TOP = 92 + RIG
    H = TOP + 2 * ROW_H + 70
    odo = Odo()
    o = sheet_frame(t, H, H - M, cols="ABCDEFGH", grid=True)
    o.append(label(M + 22, 70, "Test stand  ·  eight engagements, one reading each", t, t["accent"], 12.5))
    o.append(text(W - M - 22, 72, "Every needle stops at a number from the record below.", "serif-i", 22, t["ink3"], "end"))
    o.append(rule(M + 22, 88, W - M - 22, 88, t["rule"], 0.8))
    EY, GY = 214, 300
    rig, taps = test_rig(t, EY, GY)
    o += rig
    A0, SWEEP = 135, 270
    RT, RT0 = 24, 3.0           # re-test period, and when the first one is due
    css = []
    # the harness: a line from each tap down to its gauge, with data running along it
    for i, (tx_, ty_) in enumerate(taps):
        col, row = i % COLS, i // COLS
        x0 = M + col * CW
        gx = x0 + CW / 2
        gtop = TOP + row * ROW_H + 140 - 104 - 12
        lane = GY + 20 + i * 4.5
        if row == 0:
            d = f"M{tx_:.1f},{ty_:.1f} V{lane:.1f} H{gx:.1f} V{gtop:.1f}"
        else:
            xl = x0 + 12 + (i - 4) * 0
            d = f"M{tx_:.1f},{ty_:.1f} V{lane:.1f} H{xl:.1f} V{TOP+ROW_H+8:.1f} H{gx:.1f} V{gtop:.1f}"
        o.append(f'<path d="{d}" fill="none" stroke="{t["rule"]}" stroke-width="0.9"/>')
        o.append(f'<path d="{d}" pathLength="100" fill="none" stroke="{t["accent"]}" stroke-width="2" stroke-dasharray="3 97" '
                 f'stroke-linecap="round" class="pulse" style="animation-delay:{-i*0.37:.2f}s;animation-duration:{2.4+(i%3)*0.4:.1f}s"/>')
        o.append(f'<circle cx="{tx_:.1f}" cy="{ty_:.1f}" r="3.4" fill="{t["sheet"]}" stroke="{t["accent"]}" stroke-width="1.4"/>')
        o.append(text(tx_ + 6, ty_ + 15, f"{i+1:02d}", "mono-m", 9, t["accent"]))
    for i, (kind, val, f, ends, reading, cond) in enumerate(GAUGES):
        col, row = i % COLS, i // COLS
        x0 = M + col * CW
        y0 = TOP + row * ROW_H
        gx, gy, R = x0 + CW / 2, y0 + 140, 104
        dl = 0.3 + i * 0.18
        if col:
            o.append(rule(x0, y0 + 20, x0, y0 + ROW_H - 20, t["rule_faint"], 0.8))
        # bezel and face
        o.append(f'<circle cx="{gx:.1f}" cy="{gy}" r="{R+12}" fill="{t["deep"]}" stroke="{t["rule_strong"]}" stroke-width="1.2" class="fi"{d_(dl)}/>')
        o.append(f'<circle cx="{gx:.1f}" cy="{gy}" r="{R+6}" fill="none" stroke="{t["rule"]}" stroke-width="0.6"/>')
        o.append(f'<circle cx="{gx:.1f}" cy="{gy}" r="{R-34}" fill="url(#face)" />')

        def P(a, r):
            return gx + r * math.cos(math.radians(a)), gy + r * math.sin(math.radians(a))
        # bezel screws, slots set at random the way they are in life
        rnd_s = random.Random(i)
        for a in (45, 135, 225, 315):
            sx_, sy_ = P(a, R + 9)
            sa = rnd_s.uniform(0, 180)
            o.append(f'<g transform="translate({sx_:.1f},{sy_:.1f}) rotate({sa:.0f})"><circle r="3" fill="{t["raised"]}" stroke="{t["rule_strong"]}" stroke-width="0.7"/>'
                     f'<path d="M-2.2,0 H2.2" stroke="{t["rule_ink"]}" stroke-width="0.9"/></g>')
        # channel and status lamp: the lamp comes on once the needle settles
        o.append(text(gx - 6, gy - 44, f"CH-{i+1:02d}", "mono-m", 10, t["ink4"], "middle"))
        lx_, ly_ = gx + 22, gy - 47.5
        o.append(f'<circle cx="{lx_:.1f}" cy="{ly_}" r="3.4" fill="{t["deep"]}" stroke="{t["rule_strong"]}" stroke-width="0.7"/>')
        o.append(f'<circle cx="{lx_:.1f}" cy="{ly_}" r="7" fill="{t["ok"]}" fill-opacity=".25" class="lamp" style="animation-delay:{dl+3:.2f}s"/>'
                 f'<circle cx="{lx_:.1f}" cy="{ly_}" r="2.6" fill="{t["ok"]}" class="lamp" style="animation-delay:{dl+3:.2f}s"/>')
        o.append(f'<circle cx="{lx_:.1f}" cy="{ly_}" r="3.2" fill="{t["accent"]}" class="lampr" style="animation-delay:{dl+RT0:.2f}s"/>')
        o.append(f'<g class="lampr" style="animation-delay:{dl+RT0:.2f}s">' + text(gx, gy - 60, "RE-TEST", "mono-m", 9, t["accent"], "middle", tracking=0.14) + "</g>")
        # graduations: 50 minor, 10 major
        for c in range(5):
            dmaj, dmin = [], []
            for k in range(c * 10, c * 10 + (11 if c == 4 else 10)):
                a = A0 + SWEEP * k / 50
                major = k % 5 == 0
                x1, y1 = P(a, R - (14 if major else 8))
                x2, y2 = P(a, R)
                (dmaj if major else dmin).append(f"M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}")
            o.append(f'<g class="fi"{d_(dl+0.2+c*0.12)}><path d="{" ".join(dmin)}" stroke="{t["rule"]}" stroke-width="0.7"/>'
                     f'<path d="{" ".join(dmaj)}" stroke="{t["rule_ink"]}" stroke-width="1.3"/></g>')
        # the reading band, swept in with the needle
        ar = R - 22
        sx, sy = P(A0, ar)
        ea = A0 + SWEEP * f
        exx, eyy = P(ea, ar)
        large = 1 if SWEEP * f > 180 else 0
        o.append(f'<path d="M{sx:.1f},{sy:.1f} A{ar},{ar} 0 1 1 {P(A0+SWEEP, ar)[0]:.1f},{P(A0+SWEEP, ar)[1]:.1f}" fill="none" '
                 f'stroke="{t["rule_faint"]}" stroke-width="7"/>')
        band_d = f"M{sx:.1f},{sy:.1f} A{ar},{ar} 0 {large} 1 {exx:.1f},{eyy:.1f}"
        band_anim = (f'animation:dr 2.2s cubic-bezier(.3,.1,.3,1) {dl+0.6:.2f}s backwards,'
                     f'rb {RT}s ease-in-out {dl+RT0:.2f}s infinite')
        o.append(f'<path d="{band_d}" pathLength="1" fill="none" stroke="{t["accent"]}" stroke-width="16" stroke-opacity="{0.16 if t["glow_op"] > .5 else 0.08}" '
                 f'stroke-linecap="round" class="band" style="{band_anim}"/>')
        o.append(f'<path d="{band_d}" pathLength="1" fill="none" '
                 f'stroke="{t["accent"]}" stroke-width="7" class="band" style="{band_anim}"/>')
        # dial ends
        lx_, ly_ = P(A0 + 4, R + 30)
        o.append(text(lx_, ly_ + 4, ends[0], "mono", 12, t["ink4"], "middle"))
        lx_, ly_ = P(A0 + SWEEP - 4, R + 30)
        o.append(text(lx_, ly_ + 4, ends[1], "mono", 12, t["ink4"], "middle"))
        # needle: rests at the reading; overshoots and settles on the way in
        fin = ea
        kname = f"nd{i}"
        css.append(f"@keyframes {kname}{{0%{{transform:rotate({-SWEEP*f:.1f}deg)}}62%{{transform:rotate(6deg)}}"
                   f"78%{{transform:rotate(-2.5deg)}}90%{{transform:rotate(1deg)}}100%{{transform:rotate(0)}}}}")
        o.append(f'<g transform="translate({gx:.1f},{gy}) rotate({fin:.1f})">'
                 f'<g style="animation:{kname} 2.4s cubic-bezier(.3,.1,.3,1) {dl+0.6:.2f}s backwards">'
                 f'<g style="animation:rt{i} {RT}s ease-in-out {dl+RT0:.2f}s infinite">'
                 f'<g class="tremor" style="animation-delay:{-i*0.37:.2f}s">'
                 f'<path d="M-16,-3.2 L{R-10},-0.9 L{R-4},0 L{R-10},0.9 L-16,3.2 Z" fill="{t["accent"]}"/>'
                 f'<path d="M-16,0 H{R-6}" stroke="{t["sheet"]}" stroke-width="0.6" stroke-opacity=".6"/>'
                 '</g></g></g></g>')
        # every so often the channel is re-run: needle to zero and back, band with it
        css.append(f"@keyframes rt{i}{{0%,88%{{transform:rotate(0)}}91%{{transform:rotate({-SWEEP*f:.1f}deg)}}"
                   f"96%{{transform:rotate(4deg)}}98%{{transform:rotate(-1.5deg)}}100%{{transform:rotate(0)}}}}")
        o.append(f'<circle cx="{gx:.1f}" cy="{gy}" r="9" fill="{t["sheet"]}" stroke="{t["accent"]}" stroke-width="2"/>')
        o.append(f'<circle cx="{gx:.1f}" cy="{gy}" r="2.6" fill="{t["accent"]}"/>')
        # glass: one soft glint across the upper left
        g0, g1 = P(198, R - 6), P(250, R - 6)
        o.append(f'<path d="M{g0[0]:.1f},{g0[1]:.1f} A{R-6},{R-6} 0 0 1 {g1[0]:.1f},{g1[1]:.1f}" fill="none" stroke="#ffffff" '
                 f'stroke-opacity="{0.10 if t["glow_op"] > .5 else 0.55}" stroke-width="7" stroke-linecap="round"/>')
        # the reading itself, on drums
        s, _ = odo.number(gx, gy + 70, val, 38, t["ink"], "serif", dl + 0.6, 2.2, "middle")
        o.append(s)
        # caption
        ty = y0 + 300
        o.append(label(gx, ty, kind, t, t["accent"], 11, "middle", extra=f' class="mono-m fi"{d_(dl+0.4)}'))
        o.append(text(gx, ty + 27, reading, "sans", 18, t["ink"], "middle", extra=f' class="sans fi"{d_(dl+0.5)}'))
        o.append(text(gx, ty + 50, cond, "mono", 12, t["ink3"], "middle", extra=f' class="mono fi"{d_(dl+0.6)}'))
    o.append(rule(M + 22, H - M - 30, W - M - 22, H - M - 30, t["rule"], 0.8))
    o.append(text(M + 22, H - M - 10, "Readings are from the work itself, each with a results file or a case study behind it. "
                  "Dial ends are labelled; nothing is a score.", "mono", 12, t["ink4"]))
    defs = (f'<defs><radialGradient id="face"><stop offset="0" stop-color="{t["accent"]}" stop-opacity="{0.10 if t["glow_op"]>.5 else 0.05}"/>'
            f'<stop offset="1" stop-color="{t["accent"]}" stop-opacity="0"/></radialGradient>'
            f'<linearGradient id="hp1" x1="0" x2="1"><stop offset="0" stop-color="{t["fire_outer"]}" stop-opacity="{0.55 if t["glow_op"] > .5 else 0.35}"/>'
            f'<stop offset="1" stop-color="{t["fire_outer"]}" stop-opacity="0.05"/></linearGradient>'
            f'<linearGradient id="hp2" x1="0" x2="1"><stop offset="0" stop-color="{t["fire_core"]}"/><stop offset=".5" stop-color="{t["fire_mid"]}" stop-opacity=".8"/>'
            f'<stop offset="1" stop-color="{t["fire_mid"]}" stop-opacity="0"/></linearGradient>'
            f'<radialGradient id="hd"><stop offset="0" stop-color="{t["diamond"]}" stop-opacity=".95"/><stop offset="1" stop-color="{t["diamond"]}" stop-opacity="0"/></radialGradient>'
            '</defs>')
    css_all = (odo.css() + "".join(css) +
               ".band{stroke-dasharray:1 1;animation:dr 2.2s cubic-bezier(.3,.1,.3,1) backwards}"
               ".tremor{animation:tremor 2.9s ease-in-out infinite alternate}"
               ".pulse{animation:pulse 2.6s linear infinite}@keyframes pulse{from{stroke-dashoffset:100}to{stroke-dashoffset:0}}"
               ".hfl1,.hfl2{transform-origin:0 50%}.hfl1{animation:hfl .27s ease-in-out infinite alternate}.hfl2{animation:hfl .19s ease-in-out infinite alternate-reverse}"
               "@keyframes hfl{from{transform:scale(1,1)}to{transform:scale(1.06,.95)}}"
               ".hdia{transform-origin:50% 50%;animation:hdia .5s ease-in-out infinite alternate}@keyframes hdia{to{opacity:.5;transform:scale(1.1,.88)}}"
               "@keyframes rb{0%,88%{stroke-dashoffset:0}91%{stroke-dashoffset:1}96%,100%{stroke-dashoffset:0}}"
               ".lampr{opacity:0;animation:lampr 24s steps(1) infinite}@keyframes lampr{0%{opacity:0}87%{opacity:1}97%,100%{opacity:0}}"
               ".lamp{opacity:0;animation:lamp 3.4s ease-in-out infinite backwards}@keyframes lamp{0%{opacity:0}10%,100%{opacity:1}55%{opacity:.55}}"
               "@media (prefers-reduced-motion:reduce){.lamp{opacity:1}}"
               "@keyframes tremor{0%{transform:rotate(-.5deg)}40%{transform:rotate(.35deg)}70%{transform:rotate(-.15deg)}100%{transform:rotate(.6deg)}}")
    alt = ("Test stand. An engine fires on a thrust stand into a deflector; eight taps along it are wired to eight gauges, "
           "one per kind of work, and each channel is re-run every so often: " + "; ".join(
        f"{k}: {v} {r} ({c})" for k, v, _, _, r, c in GAUGES) + ".")
    return svg(W, H, defs + "\n".join(o), ("serif", "serif-i", "mono", "mono-m", "sans"), alt, css_all)


# --------------------------------------------------------------------------
# Plate 3: the key plan. Rooms are the domains; the names on the walls are
# the sheets filed under them. Walls are poché, doors swing in, and someone
# is always walking the corridor.
# --------------------------------------------------------------------------
def plate_keyplan(t, zones) -> str:
    """A floor plan of the work: five rooms off one corridor.

    The plotter draws the walls; then the key plan camera visits each room in
    turn, the room's light comes on, and someone in the corridor walks to its
    door. Every project carries the sheet number it has in the index below.
    """
    H = 1050
    PX0, PX1 = 84, W - 84           # inside face of the exterior walls
    RY0 = 184                       # inside face of the top wall
    ROW, HEAD, PAD, CODE = 40, 66, 18, 44
    maxn = max(len(z["projects"]) for z in zones)
    RY1 = RY0 + HEAD + maxn * ROW + 34   # room / corridor wall
    CY0, CY1 = RY1 + 6, RY1 + 6 + 66     # corridor
    EXT, PART = 12, 6
    TBY = H - M - 62
    total = sum(len(z["projects"]) for z in zones)

    # rooms share the plan by what they hold
    need = []
    for z in zones:
        longest = max(max(mono_w(p["name"], 15), mono_w(p["sub"], 11.5)) for p in z["projects"])
        need.append(max(longest + CODE + 2 * PAD, mono_w(z["title"], 11, 0.16) + 2 * PAD + 44))
    span = PX1 - PX0 - PART * (len(zones) - 1)
    scale = span / sum(need)
    widths = [w * scale for w in need]
    fs = min(1.0, scale)
    NAME, SUB, CODEF = round(15 * fs, 2), round(11.5 * fs, 2), round(11 * fs, 2)
    rooms, x = [], PX0
    for w in widths:
        rooms.append((x, w))
        x += w + PART
    doors = [rx + 26 for rx, _ in rooms]
    DW = 36

    odo_css = []
    o = sheet_frame(t, H, TBY)
    o.append(f'<defs><pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
             f'<rect width="7" height="7" fill="{t["raised"]}"/><path d="M0,0 V7" stroke="{t["rule_strong"]}" stroke-width="1.1"/></pattern>'
             f'<linearGradient id="spill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t["accent"]}" stop-opacity="{0.32 if t["glow_op"] > .5 else 0.2}"/>'
             f'<stop offset="1" stop-color="{t["accent"]}" stop-opacity="0"/></linearGradient>'
             f'<linearGradient id="rscanG" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t["accent"]}" stop-opacity="0"/>'
             f'<stop offset="1" stop-color="{t["accent"]}" stop-opacity="{0.22 if t["glow_op"] > .5 else 0.14}"/></linearGradient>'
             f'<radialGradient id="lamp"><stop offset="0" stop-color="{t["accent"]}" stop-opacity="{0.38 if t["glow_op"] > .5 else 0.22}"/>'
             f'<stop offset="1" stop-color="{t["accent"]}" stop-opacity="0"/></radialGradient></defs>')

    # ---- heading
    o.append(label(M + 22, 74, f"Key plan  ·  G-000  ·  {len(zones)} domains, {total} sheets", t, t["accent"], 12.5, extra=f' class="mono-m lt"{d_(0.1)}'))
    o.append(f'<g class="fi"{d_(0.3)}>' + text(W - M - 22, 76, "Every room is a domain; every line in it, a sheet.", "serif-i", 22, t["ink3"], "end") + "</g>")

    # ---- structural grid: bubbles over every wall line
    gl = [PX0 - EXT / 2] + [rx + w + PART / 2 for rx, w in rooms[:-1]] + [PX1 + EXT / 2]
    for i, gx in enumerate(gl):
        dl = 0.3 + i * 0.07
        o.append(f'<path d="M{gx:.1f},{126} V{CY1+EXT+30}" stroke="{t["rule_faint"]}" stroke-width="0.8" stroke-dasharray="10 4 2 4" class="fi"{d_(dl)}/>')
        o.append(f'<circle cx="{gx:.1f}" cy="112" r="12" fill="{t["sheet"]}" stroke="{t["rule_strong"]}" stroke-width="1" class="fi"{d_(dl)}/>')
        o.append(text(gx, 116.5, str(i + 1), "mono-m", 12, t["ink2"], "middle", extra=f' class="mono-m fi"{d_(dl)}'))
    # ---- dimension string: each room's width is the sheets it holds
    dy = 152
    o.append(line_pen(PX0 - EXT, dy, PX1 + EXT, dy, t["rule_strong"], 0.8, 0.5, 1.2))
    for i, (rx, w) in enumerate(rooms):
        for xx in (rx, rx + w):
            o.append(f'<path d="M{xx-4:.1f},{dy+4} L{xx+4:.1f},{dy-4} M{xx:.1f},{dy-8} V{RY0-EXT-4}" stroke="{t["rule_strong"]}" stroke-width="0.9" class="fi"{d_(0.8)}/>')
        n = len(zones[i]["projects"])
        o.append(text(rx + w / 2, dy - 7, f"{n} sheet{'s' if n != 1 else ''}", "mono", 12, t["ink3"], "middle", extra=f' class="mono fi"{d_(0.9+i*0.08)}'))

    # ---- room lights: drawn under the walls, lit by the camera's visit
    CYCLE, STOP, LOOP0 = 20.0, 4.0, 3.6
    for i, (rx, w) in enumerate(rooms):
        lx, ly = rx + w - 14, RY0 + 14
        o.append(f'<clipPath id="rm{i}"><rect x="{rx:.1f}" y="{RY0}" width="{w:.1f}" height="{RY1-RY0}"/></clipPath>')
        o.append(f'<g class="lit" clip-path="url(#rm{i})" style="animation-delay:{LOOP0+i*STOP:.2f}s">'
                 f'<rect x="{rx:.1f}" y="{RY0}" width="{w:.1f}" height="{RY1-RY0}" fill="{t["accent_soft"]}"/>'
                 f'<ellipse cx="{lx:.1f}" cy="{ly}" rx="{w*0.75:.1f}" ry="{(RY1-RY0)*0.62:.1f}" fill="url(#lamp)"/>'
                 # the camera reads the room top to bottom while it is there
                 f'<g class="rscan"><rect x="{rx:.1f}" y="{RY0-40}" width="{w:.1f}" height="40" fill="url(#rscanG)"/>'
                 f'<path d="M{rx:.1f},{RY0} H{rx+w:.1f}" stroke="{t["accent"]}" stroke-width="1.2" stroke-opacity=".8"/></g></g>')
        # and its light spills out of the door into the corridor
        d = doors[i]
        o.append(f'<path d="M{d},{RY1+3} H{d+DW} L{d+DW+30},{CY1} H{d-30} Z" fill="url(#spill)" class="lit" style="animation-delay:{LOOP0+i*STOP:.2f}s"/>')

    # ---- walls: drawn by the plotter, then filled with poché
    def wall(x, y, w, h, dl):
        o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="url(#hatch)" class="fi"{d_(dl+0.9)}/>')
        o.append(pen(f"M{x:.1f},{y:.1f} h{w:.1f} v{h:.1f} h{-w:.1f} Z", t["rule_ink"], 1.3, dl, 1.4))

    # exterior: top wall broken by a window over each room
    win = []
    x0 = PX0 - EXT
    for rx, w in rooms:
        wx = rx + w / 2 - 34
        win.append((wx, 68))
        wall(x0, RY0 - EXT, wx - x0, EXT, 0.2)
        x0 = wx + 68
    wall(x0, RY0 - EXT, PX1 + EXT - x0, EXT, 0.2)
    for wx, ww in win:
        o.append(f'<g class="fi"{d_(1.2)}><rect x="{wx:.1f}" y="{RY0-EXT}" width="{ww}" height="{EXT}" fill="{t["sheet"]}" stroke="{t["rule_ink"]}" stroke-width="1"/>'
                 f'<path d="M{wx:.1f},{RY0-EXT/2-1.5} h{ww} M{wx:.1f},{RY0-EXT/2+1.5} h{ww}" stroke="{t["rule_strong"]}" stroke-width="0.8"/></g>')
    # sides, with the entrance on the left and the stair exit on the right
    wall(PX0 - EXT, RY0, EXT, CY0 + 8 - RY0, 0.35)
    wall(PX0 - EXT, CY1 - 8, EXT, 8, 0.35)
    wall(PX1, RY0, EXT, CY0 + 8 - RY0, 0.35)
    wall(PX1, CY1 - 8, EXT, 8, 0.35)
    wall(PX0 - EXT, CY1, PX1 - PX0 + 2 * EXT, EXT, 0.45)
    # partitions
    for rx, w in rooms[:-1]:
        wall(rx + w, RY0, PART, RY1 - RY0, 0.6)
    # the corridor wall, cut by a door into every room
    x0 = PX0
    for d in doors:
        wall(x0, RY1, d - x0, PART, 0.7)
        x0 = d + DW
    wall(x0, RY1, PX1 - x0, PART, 0.7)
    for i, d in enumerate(doors):
        o.append(f'<path d="M{d+DW},{RY1} A{DW},{DW} 0 0 0 {d},{RY1-DW}" fill="none" stroke="{t["rule_strong"]}" stroke-width="0.8" stroke-dasharray="2 3" class="fi"{d_(2.2)}/>')
        o.append(f'<g transform="translate({d},{RY1})"><g class="door" style="animation-delay:{2.2+i*0.15:.2f}s">'
                 f'<rect x="-1.5" y="{-DW}" width="3" height="{DW}" fill="{t["rule_ink"]}"/></g></g>')

    # ---- rooms: tag, title, fixture, and the sheets filed inside
    for zi, (z, (rx, w)) in enumerate(zip(zones, rooms)):
        dl = 1.3 + zi * 0.18
        tx, ty = rx + PAD + 14, RY0 + 30
        o.append(f'<g transform="translate({tx:.1f},{ty})"><g class="tag"{d_(dl)}>'
                 f'<circle r="15" fill="{t["sheet"]}" stroke="{t["accent"]}" stroke-width="1.4"/>'
                 + text(0, 5, z["code"], "mono-m", 14, t["accent"], "middle") + "</g></g>")
        o.append(label(tx + 24, ty + 4.5, z["title"], t, t["ink2"], round(11 * fs, 2), extra=f' class="mono-m lt"{d_(dl+0.1)}'))
        fx, fy = rx + w - 14, RY0 + 14
        o.append(f'<g class="fi"{d_(dl+0.2)}><circle cx="{fx:.1f}" cy="{fy}" r="5.5" fill="none" stroke="{t["rule_strong"]}" stroke-width="0.9"/>'
                 f'<path d="M{fx-3.9:.1f},{fy-3.9} l7.8,7.8 M{fx+3.9:.1f},{fy-3.9} l-7.8,7.8" stroke="{t["rule_strong"]}" stroke-width="0.8"/></g>')
        o.append(f'<circle cx="{fx:.1f}" cy="{fy}" r="2.8" fill="{t["accent"]}" class="lamp" style="animation-delay:{LOOP0+zi*STOP:.2f}s"/>')
        o.append(line_pen(rx + PAD, RY0 + HEAD - 14, rx + w - PAD, RY0 + HEAD - 14, t["rule"], 0.8, dl + 0.1, 0.8))
        for i, p in enumerate(z["projects"]):
            y = RY0 + HEAD + i * ROW
            pd = dl + 0.35 + i * 0.07
            o.append(f'<g class="lt"{d_(pd)}>'
                     + text(rx + PAD, y + 13, f"{z['code']}-{i+1:02d}", "mono", CODEF, t["accent"])
                     + text(rx + PAD + CODE * fs, y + 13, p["name"], "mono-m", NAME, t["ink"])
                     + text(rx + PAD + CODE * fs, y + 30, p["sub"], "mono", SUB, t["ink4"]) + "</g>")

    # ---- corridor: stair up at the far end, the way in at the near end
    cy = (CY0 + CY1) / 2
    sx0 = PX1 - 96
    o.append(f'<g class="fi"{d_(2.0)}>' + "".join(
        f'<path d="M{sx0+k*12},{CY0+8} V{CY1-8}" stroke="{t["rule_strong"]}" stroke-width="0.8"/>' for k in range(8))
        + f'<path d="M{sx0-4},{cy} H{PX1-6}" stroke="{t["rule_ink"]}" stroke-width="1"/>'
        f'<path d="M{PX1-14},{cy-5} L{PX1-6},{cy} L{PX1-14},{cy+5}" fill="none" stroke="{t["rule_ink"]}" stroke-width="1"/>'
        + text(sx0 - 10, cy + 4, "UP", "mono-m", 11, t["ink3"], "end") + "</g>")
    o.append(f'<g class="fi"{d_(2.0)}><path d="M{PX0-58},{cy} H{PX0+8}" stroke="{t["accent_line"]}" stroke-width="1.2"/>'
             f'<path d="M{PX0},{cy-5} L{PX0+8},{cy} L{PX0},{cy+5}" fill="none" stroke="{t["accent_line"]}" stroke-width="1.2"/>'
             + text(PX0 - 58, cy - 9, "IN", "mono-m", 11, t["accent"]) + "</g>")
    o.append(f'<path d="M{PX0+20},{cy} H{sx0-30}" stroke="{t["accent_line"]}" stroke-width="1.4" stroke-dasharray="1 8" stroke-linecap="round" class="march"/>')
    o.append(text(PX0 + 20, CY1 - 10, "corridor  ·  where the ideas walk in", "mono", 11, t["ink4"]))

    # ---- the camera and the walker share one timetable
    n = len(rooms)
    kt, idx = [0.0], [n - 1]
    for i in range(n):
        kt += [(i * STOP + 0.9) / CYCLE, ((i + 1) * STOP) / CYCLE if i < n - 1 else 1.0]
        idx += [i, i]
    kt = kt[:2 * n + 1]
    idx = idx[:2 * n + 1]
    kt[-1] = 1.0
    splines = ";".join(".6 0 .2 1" if k % 2 == 0 else "0 0 1 1" for k in range(len(kt) - 1))
    kts = ";".join(f"{v:.4f}" for v in kt)
    inset = 9

    def corner(xs, y, sx, sy):
        vals = ";".join(f"{v:.1f},{y}" for v in xs)
        return (f'<g transform="translate({xs[1]:.1f},{y})"><animateTransform attributeName="transform" type="translate" '
                f'values="{vals}" keyTimes="{kts}" calcMode="spline" keySplines="{splines}" dur="{CYCLE}s" begin="{LOOP0}s" repeatCount="indefinite"/>'
                f'<path d="M0,{sy*22} V0 H{sx*22}" fill="none" stroke="{t["accent"]}" stroke-width="2.2"/></g>')
    lefts = [rooms[i][0] + inset for i in idx]
    rights = [rooms[i][0] + rooms[i][1] - inset for i in idx]
    o.append(f'<g class="fi"{d_(LOOP0-0.4)}>' + corner(lefts, RY0 + inset, 1, 1) + corner(rights, RY0 + inset, -1, 1)
             + corner(lefts, RY1 - inset, 1, -1) + corner(rights, RY1 - inset, -1, -1) + "</g>")
    # what the camera is looking at
    for i, (rx, w) in enumerate(rooms):
        k = len(zones[i]["projects"])
        o.append(f'<g class="lit" style="animation-delay:{LOOP0+i*STOP:.2f}s">'
                 + label(rx + w / 2, RY1 - inset - 3, f"{zones[i]['code']}-01 to {zones[i]['code']}-{k:02d}", t, t["accent"], round(10.5 * fs, 2), "middle")
                 + "</g>")
    span_c = (PX1 + 40) - (PX0 - 40)
    kp = ";".join(f"{(doors[i] + DW / 2 - (PX0 - 40)) / span_c:.4f}" for i in idx)
    o.append(f'<g class="fi"{d_(LOOP0-0.4)}><g>'
             f'<animateMotion path="M{PX0-40},{cy-4} H{PX1+40}" keyPoints="{kp}" keyTimes="{kts}" calcMode="spline" '
             f'keySplines="{splines}" dur="{CYCLE}s" begin="{LOOP0}s" repeatCount="indefinite" fill="freeze"/>'
             f'<circle r="15" fill="{t["accent"]}" fill-opacity=".14" class="ping"/>'
             f'<ellipse rx="9" ry="5.5" fill="{t["sheet"]}" stroke="{t["accent"]}" stroke-width="1.4"/>'
             f'<circle r="3.6" fill="{t["accent"]}"/></g></g>')

    # ---- overall dimension, compass, title block
    oy = CY1 + EXT + 24
    o.append(line_pen(PX0 - EXT, oy, PX1 + EXT, oy, t["rule_strong"], 0.8, 1.0, 1.2))
    for xx in (PX0 - EXT, PX1 + EXT):
        o.append(f'<path d="M{xx-4},{oy+4} L{xx+4},{oy-4}" stroke="{t["rule_strong"]}" stroke-width="0.9"/>')
    o.append(f'<rect x="{W/2-150}" y="{oy-9}" width="300" height="18" fill="{t["sheet"]}"/>')
    o.append(text(W / 2, oy + 4, f"{len(zones)} domains  ·  {total} sheets  ·  not to scale", "mono", 12, t["ink3"], "middle"))
    # ---- section 1-1: the building cut across its rooms, one window per sheet
    cy_cut = RY0 + HEAD - 5
    o.append(f'<path d="M{PX0-22},{cy_cut} H{PX1+22}" stroke="{t["rule_strong"]}" stroke-width="0.9" stroke-dasharray="18 4 3 4" class="fi"{d_(2.4)}/>')
    for sg, xb in ((-1, PX0 - 36), (1, PX1 + 36)):
        o.append(f'<g class="fi"{d_(2.5)}><path d="M{xb-sg*14},{cy_cut} h{sg*4}" stroke="{t["rule_ink"]}" stroke-width="2.4"/>'
                 f'<path d="M{xb-sg*12},{cy_cut} V{cy_cut-16} M{xb-sg*12-4},{cy_cut-11} L{xb-sg*12},{cy_cut-19} L{xb-sg*12+4},{cy_cut-11}" fill="none" stroke="{t["rule_ink"]}" stroke-width="1.2"/>'
                 f'<circle cx="{xb}" cy="{cy_cut}" r="8" fill="{t["sheet"]}" stroke="{t["rule_ink"]}" stroke-width="1"/>'
                 + text(xb, cy_cut + 3.6, "1", "mono-m", 10, t["ink"], "middle") + "</g>")
    sy_lab = oy + 42
    o.append(label(M + 22, sy_lab, "section 1-1  ·  one window per sheet", t, t["ink3"], 11, extra=f' class="mono-m fi"{d_(1.2)}'))
    EG = TBY - 30
    WIN, WG, PER = 24, 14, 3
    for i, ((rx, w), z) in enumerate(zip(rooms, zones)):
        n = len(z["projects"])
        rows = -(-n // PER)
        bh = 40 + rows * (WIN + 16) + 4
        by = EG - bh
        dl = 1.4 + i * 0.15
        o.append(f'<rect x="{rx:.1f}" y="{by:.1f}" width="{w:.1f}" height="{bh:.1f}" fill="{t["raised"]}" fill-opacity=".5" class="fi"{d_(dl+0.6)}/>')
        o.append(pen(f"M{rx:.1f},{EG} V{by:.1f} H{rx+w:.1f} V{EG}", t["rule_ink"], 1.3, dl, 1.2))
        o.append(pen(f"M{rx-3:.1f},{by-6:.1f} H{rx+w+3:.1f}", t["rule_ink"], 2.2, dl + 0.4, 0.6))
        o.append(text(rx + w / 2, by - 14, f"{z['code']}  ·  {n} sheet{'s' if n != 1 else ''}", "mono-m", 11, t["ink3"], "middle",
                      extra=f' class="mono-m fi"{d_(dl+0.6)}'))
        for j in range(n):
            r_, c_ = j // PER, j % PER
            in_row = min(PER, n - r_ * PER)
            row_w = in_row * WIN + (in_row - 1) * WG
            wx = rx + w / 2 - row_w / 2 + c_ * (WIN + WG)
            wy = by + 30 + r_ * (WIN + 16)
            o.append(f'<rect x="{wx:.1f}" y="{wy:.1f}" width="{WIN}" height="{WIN}" fill="{t["deep"]}" stroke="{t["rule_strong"]}" stroke-width="0.9" class="fi"{d_(dl+0.7+j*0.04)}/>')
            o.append(f'<rect x="{wx+2:.1f}" y="{wy+2:.1f}" width="{WIN-4}" height="{WIN-4}" fill="{t["accent"]}" fill-opacity=".75" class="lit" '
                     f'style="animation-delay:{LOOP0+i*STOP+0.5+j*0.22:.2f}s"/>')
            o.append(f'<path d="M{wx+WIN/2:.1f},{wy:.1f} V{wy+WIN:.1f} M{wx:.1f},{wy+WIN/2:.1f} H{wx+WIN:.1f}" stroke="{t["rule_strong"]}" stroke-width="0.7"/>')
    o.append(f'<rect x="{PX0-EXT}" y="{EG}" width="{PX1-PX0+2*EXT}" height="12" fill="url(#hatch)"/>')
    o.append(rule(PX0 - 40, EG, PX1 + 40, EG, t["rule_ink"], 1.6))

    nx, ny = W - M - 19, RY0 + 150
    o.append(f'<circle cx="{nx}" cy="{ny}" r="13" fill="{t["sheet"]}" stroke="{t["rule_strong"]}" stroke-width="0.9"/>')
    o.append(f'<path d="M{nx},{ny-18} V{ny+18}" stroke="{t["rule"]}" stroke-width="0.7"/>')
    o.append(f'<g transform="translate({nx},{ny})"><g class="needleN"><path d="M0,-12 L4.6,6 L0,2.4 L-4.6,6 Z" fill="{t["accent"]}"/></g></g>')
    o.append(text(nx, ny - 22, "N", "mono-m", 11, t["ink2"], "middle"))
    o += title_block(t, TBY, [("drawing", "Key plan", 190), ("sheet", "G-000", 130), ("domains", str(len(zones)), 130),
                              ("sheets", str(total), 120), ("scale", "NTS", 110),
                              ("note", "the corridor is where the ideas walk in", W - 2 * M - 680)])

    css = (f".rscan{{animation:rscan 3.2s cubic-bezier(.45,0,.55,1) infinite}}@keyframes rscan{{to{{transform:translateY({RY1-RY0}px)}}}}"
           ".lit{opacity:0;animation:lit 20s ease-in-out infinite backwards}"
           "@keyframes lit{0%{opacity:0}4.5%{opacity:1}19%{opacity:1}23%{opacity:0}100%{opacity:0}}"
           ".lamp{animation:lamp 20s ease-in-out infinite backwards}"
           "@keyframes lamp{0%{opacity:.25}4.5%{opacity:1}19%{opacity:1}23%{opacity:.25}100%{opacity:.25}}"
           ".door{animation:door 1.3s cubic-bezier(.3,1.5,.5,1) backwards}@keyframes door{from{transform:rotate(90deg)}}"
           ".tag{animation:tag .7s cubic-bezier(.3,1.6,.5,1) backwards}@keyframes tag{from{opacity:0;transform:scale(0)}}"
           ".march{animation:march 1.4s linear infinite}@keyframes march{to{stroke-dashoffset:-18}}"
           ".ping{transform-box:fill-box;transform-origin:50% 50%;animation:ping 2s ease-out infinite}"
           "@keyframes ping{from{transform:scale(.6);opacity:1}to{transform:scale(2.2);opacity:0}}"
           ".needleN{animation:nn 2.6s cubic-bezier(.3,1.6,.4,1) .6s backwards}@keyframes nn{from{transform:rotate(-200deg)}}")
    alt = (f"Key plan, sheet G-000: a floor plan of the work. {len(zones)} rooms off one corridor, one per domain, "
           + "; ".join(f"{z['title']} ({len(z['projects'])} sheets: " + ", ".join(p["name"] for p in z["projects"]) + ")" for z in zones)
           + ". A camera visits each room in turn: its light comes on, a scan passes down it, and the light spills into the corridor "
           "where someone stands at its door. Below, section 1-1 draws the building in elevation with one window per sheet, "
           "lit room by room in step with the camera.")
    return svg(W, H, "\n".join(o), ("serif-i", "mono", "mono-m"), alt, css)


# --------------------------------------------------------------------------
# Plate 4: the schedule of materials. Every technology, by discipline.
# --------------------------------------------------------------------------
# Projects the tracer walks through, by repository name in stack.json.
TRACE = ["AURIXA", "rebo", "FlowState", "shelf", "DADM-Aiximius", "KeepMeAwake"]
REPO_NAMES = {"rebo": "ReBo", "DADM-Aiximius": "DADM", "ai-automation-main": "ai-automation",
              "RestroScraper-PY": "RestroScraper"}


def hatch_pattern(t, i, pid):
    """Fourteen material hatches, one per discipline, the way a section legend draws them."""
    s, f = t["rule_strong"], (t["raised"] if i % 2 else t["sunk"])
    P = lambda w, h, body, rot=0: (  # noqa: E731
        f'<pattern id="{pid}" width="{w}" height="{h}" patternUnits="userSpaceOnUse"'
        + (f' patternTransform="rotate({rot})"' if rot else "") + f'><rect width="{w}" height="{h}" fill="{f}"/>{body}</pattern>')
    L = lambda d, w=0.9: f'<path d="{d}" stroke="{s}" stroke-width="{w}" fill="none"/>'  # noqa: E731
    k = i % 14
    if k == 0:
        return P(8, 8, L("M0,0 V8"), 45)
    if k == 1:
        return P(8, 8, L("M0,0 V8 M0,0 H8", 0.7), 45)
    if k == 2:
        return P(7, 7, f'<circle cx="3.5" cy="3.5" r="1.1" fill="{s}"/>')
    if k == 3:
        return P(6, 6, L("M0,3 H6", 0.8))
    if k == 4:
        return P(16, 10, L("M0,0 H16 M0,5 H16 M4,0 V5 M12,5 V10", 0.8))
    if k == 5:
        return P(8, 8, L("M0,0 V8"), -45)
    if k == 6:
        return P(12, 10, L("M0,8 L3,2 L6,8 L9,2 L12,8", 0.8))
    if k == 7:
        return P(6, 6, L("M3,0 V6", 0.8))
    if k == 8:
        rnd = random.Random(i)
        dots = "".join(f'<circle cx="{rnd.uniform(0,14):.1f}" cy="{rnd.uniform(0,14):.1f}" r="{rnd.uniform(.5,1.1):.1f}" fill="{s}"/>' for _ in range(7))
        return P(14, 14, dots)
    if k == 9:
        return P(16, 8, L("M0,4 Q4,0 8,4 T16,4", 0.8))
    if k == 10:
        return P(4, 4, L("M0,0 V4", 0.7), 45)
    if k == 11:
        return P(12, 12, f'<circle cx="6" cy="6" r="3" fill="none" stroke="{s}" stroke-width="0.8"/>')
    if k == 12:
        return P(12, 6, L("M0,3 H6", 0.9))
    return P(8, 8, L("M0,0 V8 M0,0 H8", 0.7))


def plate_schedule(t, stack, zones) -> str:
    cats = stack
    total = sum(len(c["items"]) for c in cats)
    sub_of = {p["name"]: p["sub"] for z in zones for p in z["projects"]}
    code_of = {p["name"]: f"{z['code']}-{i+1:02d}" for z in zones for i, p in enumerate(z["projects"])}
    tr = []
    for repo in TRACE:
        name = REPO_NAMES.get(repo, repo)
        used = [{it["name"] for it in c["items"] if repo in it.get("repos", [])} for c in cats]
        tr.append(dict(repo=repo, name=name, sub=sub_of.get(name, ""), code=code_of.get(name, ""),
                       used=used, n=sum(len(u) for u in used), d=sum(1 for u in used if u)))
    NS = len(tr)
    slot = [[] for _ in tr]     # everything one traced project lights, gathered into one layer
    chip_text = []
    STOP, LOOP0 = 4.0, 4.6
    CYCLE = STOP * NS

    # ---- schedule geometry first: it decides the height
    X0, X1 = 52, W - 52
    LAB = 214
    CX0 = X0 + LAB + 14
    CH, GAP, PADX, RG, SP = 26, 6, 8, 6, 14
    FS, FC = 12, 9.5
    layout = []
    for c in cats:
        lines, cur, cw = [], [], 0.0
        for it in c["items"]:
            w = mono_w(it["name"], FS) + 6 + mono_w(str(it["n"]), FC) + 2 * PADX
            if cur and cw + GAP + w > X1 - 14 - CX0:
                lines.append(cur)
                cur, cw = [], 0.0
            cur.append((it, w))
            cw += (GAP if cw else 0) + w
        if cur:
            lines.append(cur)
        h = max(84, SP * 2 + len(lines) * (CH + RG) - RG)
        layout.append((c, lines, h))

    EY0 = 128
    thick = [16 + 20 * len(c["items"]) / max(len(x["items"]) for x in cats) for c in cats]
    EY1 = EY0 + sum(thick)
    SY0 = EY1 + 96
    SY1 = SY0 + 36 + sum(h for _, _, h in layout)
    H = SY1 + 92
    o = sheet_frame(t, H, H - M, grid=False)
    o.append("<defs>" + "".join(hatch_pattern(t, i, f"m{i}") for i in range(len(cats))) +
             f'<pattern id="earth" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
             f'<path d="M0,0 V10" stroke="{t["rule_strong"]}" stroke-width="0.8"/></pattern></defs>')

    # ---- heading
    o.append(label(M + 22, 74, f"Schedule of materials  ·  A-102  ·  {total} items, {len(cats)} disciplines", t, t["accent"], 12.5,
                   extra=f' class="mono-m lt"{d_(0.1)}'))
    o.append(f'<g class="fi"{d_(0.3)}>' + text(W - M - 22, 76, "Trace a project, and the schedule lights up.", "serif-i", 22, t["ink3"], "end") + "</g>")
    o.append(rule(M + 22, 92, W - M - 22, 92, t["rule"], 0.8))

    # ---- the wall section: one stratum per discipline, laid from the ground up
    EX0, EX1, LX = 452, 800, 836
    y = EY0
    mids = []
    for i, (c, th) in enumerate(zip(cats, thick)):
        dl = 0.3 + (len(cats) - 1 - i) * 0.11
        o.append(f'<g class="lay"{d_(dl)}><rect x="{EX0}" y="{y:.1f}" width="{EX1-EX0}" height="{th:.1f}" fill="url(#m{i})" '
                 f'stroke="{t["rule_ink"]}" stroke-width="1"/></g>')
        mids.append(y + th / 2)
        for k, tk in enumerate(tr):
            f = len(tk["used"][i]) / len(c["items"])
            if f:
                wv = (EX1 - EX0) * f
                slot[k].append(f'<rect x="{EX0}" y="{y:.1f}" width="{wv:.1f}" height="{th:.1f}" fill="{t["accent"]}" fill-opacity=".42"/>'
                               f'<path d="M{EX0+wv:.1f},{y:.1f} v{th:.1f}" stroke="{t["accent"]}" stroke-width="2"/>')
        y += th
    # ground and footing
    o.append(f'<rect x="{EX0-40}" y="{EY1}" width="{EX1-EX0+80}" height="16" fill="url(#earth)" class="fi"{d_(0.2)}/>')
    o.append(rule(EX0 - 60, EY1, EX1 + 20, EY1, t["rule_ink"], 1.6))
    o.append(line_pen(EX0 - 18, EY0, EX0 - 18, EY1, t["rule_strong"], 0.8, 1.2, 1.0))
    for yy in (EY0, EY1):
        o.append(f'<path d="M{EX0-22},{yy+4} L{EX0-14},{yy-4}" stroke="{t["rule_strong"]}" stroke-width="0.9" class="fi"{d_(1.6)}/>')
    o.append(f'<g class="fi"{d_(1.8)}>' + text(EX0 - 26, (EY0 + EY1) / 2, f"{total} items", "mono", 12, t["ink3"], "middle",
                                               extra=f' class="mono" transform="rotate(-90 {EX0-26} {(EY0+EY1)/2:.1f})"') + "</g>")
    # leaders out to the legend
    gap = (EY1 - EY0) / len(cats)
    for i, (c, ym) in enumerate(zip(cats, mids)):
        ly = EY0 + gap * (i + 0.5)
        dl = 1.6 + i * 0.05
        o.append(f'<circle cx="{EX1}" cy="{ym:.1f}" r="2.4" fill="{t["accent"]}" class="fi"{d_(dl)}/>')
        o.append(pen(f"M{EX1},{ym:.1f} L{LX-14},{ly:.1f} H{LX-4}", t["accent_line"], 0.9, dl, 0.6))
        o.append(f'<g class="fi"{d_(dl+0.3)}>' + text(LX, ly + 4, f"{i+1:02d}", "mono-m", 11.5, t["accent"])
                 + label(LX + 26, ly + 4, c["category"], t, t["ink2"], 11)
                 + text(W - M - 22, ly + 4, str(len(c["items"])), "mono-m", 12, t["ink3"], "end") + "</g>")

    # ---- the tracer's read-out
    HX = 70
    o.append(label(HX, 146, "tracing", t, t["accent"], 12, extra=f' class="mono-m fi"{d_(LOOP0-0.6)}'))
    o.append(f'<circle cx="{HX+76}" cy="142" r="4" fill="{t["accent"]}" class="blink"/>')
    for k, tk in enumerate(tr):
        slot[k].append(text(HX, 204, tk["name"], "serif", 54, t["ink"])
                       + text(HX + 2, 232, tk["sub"], "serif-i", 20, t["ink3"])
                       + text(HX, 312, str(tk["n"]), "serif", 72, t["accent"])
                       + text(HX + 2, 338, f"materials across {tk['d']} disciplines", "mono", 12.5, t["ink2"]))
    qy = 382
    o.append(rule(HX, qy - 18, HX + 330, qy - 18, t["rule"], 0.8))
    for k, tk in enumerate(tr):
        yy = qy + k * 24
        o.append(text(HX + 18, yy + 4, tk["code"], "mono", 11.5, t["ink4"]) + text(HX + 72, yy + 4, tk["name"], "mono-m", 13, t["ink3"])
                 + text(HX + 330, yy + 4, f"{tk['n']}", "mono", 12, t["ink4"], "end"))
        slot[k].append(f'<rect x="{HX}" y="{yy-11}" width="334" height="22" fill="{t["accent_soft"]}"/>'
                       f'<circle cx="{HX+7}" cy="{yy}" r="3.2" fill="{t["accent"]}"/>'
                       + text(HX + 72, yy + 4, tk["name"], "mono-m", 13, t["accent"]))

    # ---- the schedule itself
    o.append(rule(X0, SY0, X1, SY0, t["rule_strong"], 1.2))
    o.append(label(X0 + 14, SY0 + 24, "discipline", t, t["ink4"], 11))
    o.append(label(CX0, SY0 + 24, "material", t, t["ink4"], 11))
    o.append(text(X1 - 14, SY0 + 24, "the small number is how many repos or engagements use it", "mono", 11.5, t["ink4"], "end"))
    y = SY0 + 36
    for ci, (c, lines, sh) in enumerate(layout):
        dl = 0.6 + ci * 0.1
        o.append(rule(X0, y, X1, y, t["rule"], 0.8))
        o.append(f'<rect x="{X0}" y="{y}" width="{LAB}" height="{sh}" fill="{t["sunk"]}" fill-opacity=".7"/>')
        o.append(rule(X0 + LAB, y, X0 + LAB, y + sh, t["rule"], 0.8))
        o.append(f'<rect x="{X0+14}" y="{y+16}" width="40" height="24" fill="url(#m{ci})" stroke="{t["rule_ink"]}" stroke-width="0.9"/>')
        words, lab_lines, cur = c["category"].split(" "), [], ""
        for wd in words:
            trial = (cur + " " + wd).strip()
            if mono_w(trial, 11.5, 0.16) > LAB - 82 and cur:
                lab_lines.append(cur)
                cur = wd
            else:
                cur = trial
        lab_lines.append(cur)
        o.append(text(X0 + 66, y + 27, f"{ci+1:02d}", "mono-m", 11.5, t["accent"]))
        for i, ll in enumerate(lab_lines):
            o.append(label(X0 + 92, y + 27 + i * 16, ll, t, t["ink2"], 11.5))
        o.append(text(X0 + LAB - 14, y + sh - 14, str(len(c["items"])), "serif", 32, t["ink4"], "end"))
        for k, tk in enumerate(tr):
            u = len(tk["used"][ci])
            msg = f"{tk['name']} · {u}" if u else f"{tk['name']} · none"
            slot[k].append(text(X0 + 14, y + sh - 16, msg, "mono-m", 11.5, t["accent"] if u else t["ink4"]))
        for li, line in enumerate(lines):
            cy = y + SP + li * (CH + RG)
            x = CX0
            for j, (it, w) in enumerate(line):
                heavy = it["n"] >= 3
                fill = t["raised"] if heavy else "none"
                stroke = t["rule_strong"] if heavy else t["rule"]
                slots = [k for k, tk in enumerate(tr) if it["name"] in tk["used"][ci]]
                for k in slots:
                    slot[k].append(f'<rect x="{x-2.5:.1f}" y="{cy-2.5}" width="{w+5:.1f}" height="{CH+5}" rx="5" fill="none" '
                                   f'stroke="{t["accent"]}" stroke-opacity=".3" stroke-width="3"/>'
                                   f'<rect x="{x:.1f}" y="{cy}" width="{w:.1f}" height="{CH}" rx="3" fill="{t["accent"]}" '
                                   f'fill-opacity="{0.34 if t["glow_op"] > .5 else 0.22}" stroke="{t["accent"]}" stroke-width="1.8"/>')
                cd_ = d_(dl + li * 0.04 + j * 0.02)
                o.append(f'<rect x="{x:.1f}" y="{cy}" width="{w:.1f}" height="{CH}" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="0.9" class="chip"{cd_}/>')
                chip_text.append(f'<g class="chip"{cd_}>'
                                 + text(x + PADX, cy + 17.5, it["name"], "mono-m" if heavy else "mono", FS, t["ink"])
                                 + text(x + w - PADX, cy + 17.5, str(it["n"]), "mono", FC, t["ink4"], "end") + "</g>")
                x += w + GAP
        y += sh
    # each project's highlights move as one layer: frames, then highlights, then the words on top
    o += [f'<g class="hl s{k}">' + "".join(parts) + "</g>" for k, parts in enumerate(slot)]
    o += chip_text
    o.append(rule(X0, y, X1, y, t["rule_strong"], 1.2))
    ly = y + 26
    o.append(label(X0 + 14, ly + 12, "legend", t, t["ink4"], 11))
    o.append(f'<rect x="{CX0}" y="{ly}" width="22" height="16" rx="3" fill="{t["raised"]}" stroke="{t["rule_strong"]}" stroke-width="0.9"/>')
    o.append(text(CX0 + 32, ly + 12.5, "in three or more", "mono-m", 12.5, t["ink3"]))
    o.append(f'<rect x="{CX0+196}" y="{ly}" width="22" height="16" rx="3" fill="none" stroke="{t["rule"]}" stroke-width="0.9"/>')
    o.append(text(CX0 + 228, ly + 12.5, "in one or two", "mono", 12.5, t["ink3"]))
    o.append(f'<rect x="{CX0+380}" y="{ly}" width="22" height="16" rx="3" fill="{t["accent"]}" fill-opacity=".34" stroke="{t["accent"]}" stroke-width="1.8"/>')
    o.append(text(CX0 + 412, ly + 12.5, "used by the project being traced", "mono", 12.5, t["ink3"]))

    css = (".lay{animation:lay .8s cubic-bezier(.3,1.4,.5,1) backwards}@keyframes lay{from{opacity:0;transform:translateY(-26px)}}"
           ".chip{animation:chip .6s cubic-bezier(.2,.8,.2,1) backwards}@keyframes chip{from{opacity:0;transform:translateY(8px)}}"
           f".hl{{opacity:0;animation:hl {CYCLE:.0f}s ease-in-out infinite backwards}}"
           f"@keyframes hl{{0%{{opacity:0}}{100*0.5/CYCLE:.2f}%{{opacity:1}}{100*(STOP-0.35)/CYCLE:.2f}%{{opacity:1}}{100*STOP/CYCLE:.2f}%,100%{{opacity:0}}}}"
           + "".join(f".s{k}{{animation-delay:{LOOP0+k*STOP:.2f}s}}" for k in range(NS))
           + ".blink{animation:blink 1.2s steps(2) infinite}@keyframes blink{50%{opacity:0}}"
           "@media (prefers-reduced-motion:reduce){.s0{opacity:1}}")
    alt = (f"Schedule of materials, sheet A-102: {total} items across {len(cats)} disciplines, every tool from every repository and engagement. "
           "A wall section stacks one stratum per discipline, thick by how many items it holds. A tracer walks through six projects, "
           + ", ".join(f"{tk['name']} ({tk['n']} materials)" for tk in tr)
           + ", and lights every material each one uses. The full list is in text below.")
    return svg(W, H, "\n".join(o), ("serif", "serif-i", "mono", "mono-m"), alt, css)


# --------------------------------------------------------------------------
# Plate 4b: the sheet index, one card per sheet. Each card is its own image so
# the README can link it to its repository; each domain has its own live
# figure, varied per sheet.
# --------------------------------------------------------------------------
CARD_W, CARD_H = 600, 410


def motif(t, code, seed, x0, y0, w, h):
    """A small working drawing for the card's domain, in a box at (x0, y0)."""
    rnd = random.Random(seed)
    acc, ink, faint, strong = t["accent"], t["rule_ink"], t["rule"], t["rule_strong"]
    o = [f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" rx="4" fill="{t["deep"]}" stroke="{strong}" stroke-width="0.9"/>',
         f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" rx="4" fill="url(#cg)"/>']
    cx = lambda f: x0 + w * f  # noqa: E731
    cy = lambda f: y0 + h * f  # noqa: E731
    if code == "A":
        # a small network; signals run along its edges
        layers = [[cy(0.5)], sorted(rnd.uniform(0.18, 0.82) for _ in range(rnd.choice((3, 4)))), [cy(0.32), cy(0.68)], [cy(0.5)]]
        layers[1] = [cy(v) for v in layers[1]]
        xs = [cx(0.12), cx(0.4), cx(0.68), cx(0.9)]
        k = 0
        for li in range(3):
            for ya in layers[li]:
                for yb in layers[li + 1]:
                    d = f"M{xs[li]:.1f},{ya:.1f} L{xs[li+1]:.1f},{yb:.1f}"
                    o.append(f'<path d="{d}" stroke="{faint}" stroke-width="0.8"/>')
                    if rnd.random() < 0.6:
                        o.append(f'<path d="{d}" pathLength="1" stroke="{acc}" stroke-width="1.8" stroke-linecap="round" '
                                 f'class="sig" style="animation-delay:{-rnd.uniform(0, 2.4):.2f}s;animation-duration:{rnd.uniform(1.6, 2.6):.2f}s"/>')
                    k += 1
        for li, col in enumerate(layers):
            for ya in col:
                o.append(f'<circle cx="{xs[li]:.1f}" cy="{ya:.1f}" r="5" fill="{t["sheet"]}" stroke="{ink}" stroke-width="1.1"/>')
                o.append(f'<circle cx="{xs[li]:.1f}" cy="{ya:.1f}" r="2.4" fill="{acc}" class="node" style="animation-delay:{-rnd.uniform(0, 2):.2f}s"/>')
    elif code == "V":
        # a viewfinder: a scan line, two subjects, a box that finds each in turn
        a = (cx(rnd.uniform(0.18, 0.32)), cy(0.38), 26, 46)
        b = (cx(rnd.uniform(0.56, 0.68)), cy(0.52), 40, 26)
        o.append(f'<rect x="{a[0]:.1f}" y="{a[1]:.1f}" width="{a[2]}" height="{a[3]}" rx="12" fill="none" stroke="{strong}" stroke-width="1"/>')
        o.append(f'<circle cx="{a[0]+13:.1f}" cy="{a[1]-8:.1f}" r="7" fill="none" stroke="{strong}" stroke-width="1"/>')
        o.append(f'<rect x="{b[0]:.1f}" y="{b[1]:.1f}" width="{b[2]}" height="{b[3]}" rx="5" fill="none" stroke="{strong}" stroke-width="1"/>')
        o.append(f'<circle cx="{b[0]+9:.1f}" cy="{b[1]+b[3]:.1f}" r="4" fill="none" stroke="{strong}" stroke-width="1"/>'
                 f'<circle cx="{b[0]+31:.1f}" cy="{b[1]+b[3]:.1f}" r="4" fill="none" stroke="{strong}" stroke-width="1"/>')
        for (bx, by, bw, bh), cls, sc in (((a[0] - 5, a[1] - 20, a[2] + 10, a[3] + 26), "boxa", "0.97"), ((b[0] - 5, b[1] - 6, b[2] + 10, b[3] + 16), "boxb", "0.91")):
            o.append(f'<g class="{cls}"><rect x="{bx:.1f}" y="{by:.1f}" width="{bw}" height="{bh}" fill="{t["accent_soft"]}" stroke="{acc}" stroke-width="1.5"/>'
                     f'<rect x="{bx:.1f}" y="{by-12:.1f}" width="30" height="12" fill="{acc}"/>'
                     + text(bx + 3, by - 3, sc, "mono-m", 8.5, t["sheet"]) + "</g>")
        o.append(f'<g class="scanv"><path d="M{x0+4},{y0+6} H{x0+w-4}" stroke="{acc}" stroke-width="1" stroke-opacity=".7"/></g>')
        for (px, py, sx, sy) in ((x0 + 8, y0 + 8, 1, 1), (x0 + w - 8, y0 + 8, -1, 1), (x0 + 8, y0 + h - 8, 1, -1), (x0 + w - 8, y0 + h - 8, -1, -1)):
            o.append(f'<path d="M{px},{py+sy*12} V{py} H{px+sx*12}" fill="none" stroke="{ink}" stroke-width="1.3"/>')
        o.append(f'<circle cx="{x0+w-16}" cy="{y0+18}" r="3.5" fill="#e5484d" class="blink"/>')
        o.append(text(x0 + w - 24, y0 + 21, "REC", "mono-m", 8, t["ink3"], "end"))
    elif code == "D":
        # records stream into a store; the store's level breathes
        sx, sy, rw, rh = cx(0.7), cy(0.3), 26, 54
        o.append(f'<path d="M{sx-rw},{sy} V{sy+rh} A{rw},8 0 0 0 {sx+rw},{sy+rh} V{sy}" fill="{t["sheet"]}" stroke="{ink}" stroke-width="1.2"/>')
        o.append(f'<g class="level"><path d="M{sx-rw+2},{sy+rh*0.45} A{rw-2},7 0 0 0 {sx+rw-2},{sy+rh*0.45} V{sy+rh} A{rw-2},7 0 0 1 {sx-rw+2},{sy+rh} Z" '
                 f'fill="{acc}" fill-opacity=".35"/></g>')
        o.append(f'<ellipse cx="{sx}" cy="{sy}" rx="{rw}" ry="8" fill="{t["raised"]}" stroke="{ink}" stroke-width="1.2"/>')
        for k in (0.33, 0.66):
            o.append(f'<path d="M{sx-rw},{sy+rh*k} A{rw},8 0 0 0 {sx+rw},{sy+rh*k}" fill="none" stroke="{faint}" stroke-width="0.8"/>')
        for r in range(4):
            yy = cy(0.25) + r * 16
            o.append(f'<rect x="{cx(0.08):.1f}" y="{yy:.1f}" width="{w*0.26:.1f}" height="10" fill="none" stroke="{faint}" stroke-width="0.8"/>')
        for k in range(5):
            yy = cy(0.25) + rnd.randrange(4) * 16
            o.append(f'<rect x="{cx(0.08):.1f}" y="{yy:.1f}" width="12" height="10" rx="2" fill="{acc}" class="rec" '
                     f'style="--dx:{sx-rw-cx(0.08)-6:.1f}px;--dy:{sy+rh*0.5-yy-5:.1f}px;animation-delay:{-k*0.55:.2f}s"/>')
    elif code == "W":
        # a browser; pages turn over in it, a cursor clicks through
        bx, by, bw, bh = x0 + 10, y0 + 12, w - 20, h - 24
        o.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="4" fill="{t["sheet"]}" stroke="{ink}" stroke-width="1.1"/>')
        o.append(f'<path d="M{bx},{by+13} H{bx+bw}" stroke="{faint}" stroke-width="0.8"/>')
        for i in range(3):
            o.append(f'<circle cx="{bx+8+i*7}" cy="{by+6.5}" r="2.2" fill="{acc if i == 0 else faint}"/>')
        o.append(f'<clipPath id="pg{seed}"><rect x="{bx+1}" y="{by+14}" width="{bw-2}" height="{bh-15}"/></clipPath>')
        pages = []
        for pi in range(2):
            r2 = random.Random(seed * 7 + pi)
            g = [f'<rect x="{bx+8}" y="{by+22}" width="{bw*r2.uniform(0.4,0.6):.1f}" height="9" fill="{t["ink2"]}" fill-opacity=".6"/>',
                 f'<rect x="{bx+8}" y="{by+36}" width="{bw*0.8:.1f}" height="4" fill="{faint}"/>',
                 f'<rect x="{bx+8}" y="{by+44}" width="{bw*0.62:.1f}" height="4" fill="{faint}"/>']
            for c in range(3):
                g.append(f'<rect x="{bx+8+c*(bw-16)/3:.1f}" y="{by+56}" width="{(bw-16)/3-5:.1f}" height="{bh-64:.1f}" rx="2" fill="none" '
                         f'stroke="{acc if (c == r2.randrange(3)) else faint}" stroke-width="0.9"/>')
            pages.append(f'<g class="page{pi}">' + "".join(g) + "</g>")
        o.append(f'<g clip-path="url(#pg{seed})">' + "".join(pages) + "</g>")
        o.append(f'<g class="cursor"><path d="M0,0 V13 L3.5,10 L6,15 L8,14 L5.5,9 H10 Z" fill="{t["ink"]}" stroke="{t["sheet"]}" stroke-width="0.8"/>'
                 f'<circle r="7" fill="none" stroke="{acc}" stroke-width="1.2" class="click"/></g>')
    else:
        # a training run: loss falls, points settle
        ax0, ay0, ax1, ay1 = x0 + 16, y0 + h - 16, x0 + w - 10, y0 + 12
        o.append(f'<path d="M{ax0},{ay1} V{ay0} H{ax1}" fill="none" stroke="{ink}" stroke-width="1"/>')
        for k in range(1, 4):
            yy = ay0 - (ay0 - ay1) * k / 4
            o.append(f'<path d="M{ax0},{yy:.1f} H{ax1}" stroke="{faint}" stroke-width="0.6" stroke-dasharray="2 3"/>')
        a_ = rnd.uniform(3.5, 5.5)
        pts = []
        for i in range(31):
            f = i / 30
            v = math.exp(-a_ * f) * 0.85 + 0.08 + rnd.uniform(-0.03, 0.03)
            pts.append((ax0 + (ax1 - ax0) * f, ay0 - (ay0 - ay1) * v))
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        o.append(f'<path d="{d}" pathLength="1" fill="none" stroke="{acc}" stroke-width="1.6" class="loss"/>')
        val = [(x, y + (ay0 - ay1) * rnd.uniform(0.04, 0.1)) for x, y in pts[::5]]
        for i, (x, y) in enumerate(val):
            o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.3" fill="none" stroke="{t["ink2"]}" stroke-width="1" class="pt" style="animation-delay:{i*0.35:.2f}s"/>')
        o.append(text(ax1, ay1 + 8, "loss", "mono", 8.5, t["ink4"], "end"))
    return "".join(o)


MOTIF_CSS = (
    ".sig{stroke-dasharray:.12 .88;animation:sig 2s linear infinite}@keyframes sig{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}"
    ".node{animation:node 2.2s ease-in-out infinite alternate}@keyframes node{from{opacity:.25}to{opacity:1}}"
    ".boxa{animation:boxa 5s steps(1) infinite}@keyframes boxa{0%{opacity:1}50%{opacity:0}}"
    ".boxb{opacity:0;animation:boxb 5s steps(1) infinite}@keyframes boxb{0%{opacity:0}50%{opacity:1}}"
    ".scanv{animation:scanv 2.5s ease-in-out infinite alternate}@keyframes scanv{to{transform:translateY(104px)}}"
    ".blink{animation:blink 1.2s steps(2) infinite}@keyframes blink{50%{opacity:0}}"
    ".rec{opacity:0;transform-box:fill-box;transform-origin:50% 50%;animation:rec 2.75s cubic-bezier(.5,0,.5,1) infinite}"
    "@keyframes rec{0%{opacity:0;transform:translate(0,0)}15%{opacity:1}85%{opacity:1}100%{opacity:0;transform:translate(var(--dx),var(--dy)) scale(.4)}}"
    ".level{animation:level 3s ease-in-out infinite alternate}@keyframes level{to{transform:translateY(-10px)}}"
    ".page0{animation:pg0 7s cubic-bezier(.6,0,.2,1) infinite}.page1{animation:pg1 7s cubic-bezier(.6,0,.2,1) infinite}"
    "@keyframes pg0{0%,40%{transform:translateX(0);opacity:1}50%,90%{transform:translateX(-40px);opacity:0}100%{transform:translateX(0);opacity:1}}"
    "@keyframes pg1{0%,40%{transform:translateX(40px);opacity:0}50%,90%{transform:translateX(0);opacity:1}100%{transform:translateX(-40px);opacity:0}}"
    ".cursor{animation:cur 7s ease-in-out infinite}"
    "@keyframes cur{0%{transform:translate(500px,90px)}30%,38%{transform:translate(520px,108px)}70%,78%{transform:translate(470px,100px)}100%{transform:translate(500px,90px)}}"
    ".click{opacity:0;transform-box:fill-box;transform-origin:50% 50%;animation:click 3.5s ease-out 1.2s infinite}"
    "@keyframes click{0%{opacity:1;transform:scale(.3)}25%{opacity:0;transform:scale(1.8)}100%{opacity:0}}"
    ".loss{stroke-dasharray:1 1;animation:loss 6s cubic-bezier(.3,0,.3,1) infinite}"
    "@keyframes loss{0%{stroke-dashoffset:1}55%,90%{stroke-dashoffset:0;opacity:1}100%{stroke-dashoffset:0;opacity:0}}"
    ".pt{opacity:0;animation:pt 6s ease-out infinite}@keyframes pt{0%{opacity:0}10%,88%{opacity:1}100%{opacity:0}}"
    "@media (prefers-reduced-motion:reduce){.rec,.click{display:none}.boxb,.pt{opacity:1}}"
)


def card(t, zone, i, p, seed) -> str:
    W_, H_ = CARD_W, CARD_H
    code = f"{zone['code']}-{i+1:02d}"
    o = [f'<defs><radialGradient id="cg" cx="50%" cy="40%" r="70%"><stop offset="0" stop-color="{t["accent"]}" '
         f'stop-opacity="{0.10 if t["glow_op"] > .5 else 0.06}"/><stop offset="1" stop-color="{t["accent"]}" stop-opacity="0"/></radialGradient>'
         f'{grid_defs(t, "cgr", 12, 60)}</defs>',
         f'<rect x="1" y="1" width="{W_-2}" height="{H_-2}" rx="10" fill="{t["sheet"]}" stroke="{t["rule_strong"]}" stroke-width="1.2"/>',
         f'<rect x="1" y="1" width="{W_-2}" height="{H_-2}" rx="10" fill="url(#cgrM)" opacity=".7"/>',
         pen(f"M11,11 H{W_-11} V{H_-11} H11 Z", t["rule"], 0.8, 0.05, 1.4)]
    for (px, py, sx, sy) in ((5, 5, 1, 1), (W_ - 5, 5, -1, 1), (5, H_ - 5, 1, -1), (W_ - 5, H_ - 5, -1, -1)):
        o.append(f'<path d="M{px},{py+sy*10} V{py} H{px+sx*10}" fill="none" stroke="{t["accent_line"]}" stroke-width="1.2"/>')
    # number and domain
    o.append(f'<rect x="26" y="26" width="58" height="24" rx="3" fill="{t["accent"]}"/>')
    o.append(text(55, 43, code, "mono-m", 13, t["sheet"], "middle"))
    o.append(label(96, 43, zone["title"], t, t["ink4"], 11.5))
    o.append(f'<g class="up"{d_(0.15)}>' + text(24, 102, p["name"], "serif", 46 if len(p["name"]) < 15 else 38, t["ink"]) + "</g>")
    o.append(text(26, 130, p["sub"], "mono", 14, t["ink3"], extra=f' class="mono fi"{d_(0.3)}'))
    o.append(motif(t, zone["code"], seed, 432, 22, 144, 116))
    o.append(line_pen(26, 150, W_ - 26, 150, t["rule"], 0.8, 0.3, 1.0))
    # the description: as large as it can be and still fit
    for size, lh in ((18, 25.5), (17, 24), (16, 22.5), (15, 21)):
        lines = wrap(p["desc"], size, W_ - 54, 0.535)
        if 180 + (len(lines) - 1) * lh <= H_ - 92:
            break
    for k, ln in enumerate(lines):
        o.append(text(26, 180 + k * lh, ln, "sans", size, t["ink2"], extra=f' class="sans fi"{d_(0.35+k*0.06)}'))
    # stack, as chips, as many as the row holds
    x, ty = 26, H_ - 76
    shown = 0
    for s in p.get("stack", []):
        cw = mono_w(s, 12) + 16
        if x + cw > W_ - 64:
            break
        o.append(f'<rect x="{x:.1f}" y="{ty}" width="{cw:.1f}" height="24" rx="3" fill="none" stroke="{t["rule"]}" stroke-width="0.9"/>')
        o.append(text(x + 8, ty + 16.5, s, "mono", 12, t["ink2"]))
        x += cw + 6
        shown += 1
    rest = len(p.get("stack", [])) - shown
    if rest > 0:
        o.append(text(x + 2, ty + 16.5, f"+{rest}", "mono-m", 12, t["ink4"]))
    # foot: where it lives
    fy = H_ - 30
    o.append(rule(26, fy - 12, W_ - 26, fy - 12, t["rule_faint"], 0.8))
    if p.get("href"):
        o.append(text(26, fy + 6, p["href"].replace("https://", ""), "mono", 12.5, t["ink4"]))
        o.append(label(W_ - 48, fy + 6, "open", t, t["accent"], 12.5, "end"))
        o.append(f'<path d="M{W_-40},{fy+6} L{W_-28},{fy-6} M{W_-38},{fy-6} H{W_-28} V{fy+4}" fill="none" stroke="{t["accent"]}" stroke-width="1.5"/>')
    else:
        o.append(text(26, fy + 6, "private · described here, not linked", "mono", 12.5, t["ink4"]))
        o.append(f'<rect x="{W_-118}" y="{fy-10}" width="92" height="22" rx="3" fill="none" stroke="{t["accent"]}" stroke-width="1.2"/>')
        o.append(label(W_ - 72, fy + 5.5, "private", t, t["accent"], 12, "middle"))
    alt = f"{code} · {p['name']}: {p['desc']}" + (f" Stack: {', '.join(p['stack'])}." if p.get("stack") else "")
    return svg(W_, H_, "\n".join(o), ("serif", "mono", "mono-m", "sans"), alt, MOTIF_CSS)


def zone_band(t, zone) -> str:
    H_ = 74
    n = len(zone["projects"])
    o = [f'<g class="tag" transform="translate(22,40)"><circle r="17" fill="{t["sheet"]}" stroke="{t["accent"]}" stroke-width="1.6"/>'
         + text(0, 5.5, zone["code"], "mono-m", 16, t["accent"], "middle") + "</g>",
         f'<g class="lt"{d_(0.15)}>' + text(54, 52, zone["title"], "serif", 38, t["ink"]) + "</g>",
         line_pen(54, 66, W, 66, t["rule"], 0.9, 0.2, 1.4),
         label(W, 50, f"{zone['code']}-01 to {zone['code']}-{n:02d}  ·  {n} sheet{'s' if n != 1 else ''}", t, t["ink4"], 12, "end")]
    css = ".tag{animation:tag .7s cubic-bezier(.3,1.6,.5,1) backwards}@keyframes tag{from{opacity:0;transform:translate(22px,40px) scale(0)}}"
    return svg(W, H_, "\n".join(o), ("serif", "mono-m"), f"{zone['code']} · {zone['title']}, {n} sheets", css)


def index_markdown(zones) -> str:
    """The README's sheet index: a band per domain, then its cards two to a row."""
    def pic(path, alt, width=None):
        w = f' width="{width}"' if width else ' width="100%"'
        return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="assets/dark/{path}">'
                f'<img src="assets/light/{path}"{w} alt="{escape(alt, {chr(34): "&quot;"})}"></picture>')

    out = []
    for z in zones:
        block = [pic(f"cards/zone-{z['code'].lower()}.svg", f"{z['code']} · {z['title']}"), "", '<p align="center">']
        for i, p in enumerate(z["projects"]):
            code = f"{z['code']}-{i+1:02d}"
            alt = f"{code} · {p['name']}: {p['desc']}"
            img = pic(f"cards/{code.lower()}.svg", alt, "49%")
            block.append(f'<a href="{p["href"]}">{img}</a>' if p.get("href") else img)
        block.append("</p>")
        if z["code"] == "R":
            out += ["<details>", f"<summary><b>R-01 to R-{len(z['projects']):02d}</b> · research notebooks from earlier flight tests</summary>",
                    "<br>", ""] + block + ["", "</details>"]
        else:
            out += block + [""]
    return "\n" + "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------
# Plate 5: telemetry. Counts only; no grades, no ranks.
# --------------------------------------------------------------------------
def day_stats(days):
    counts = [d["c"] for d in days]
    active = sum(1 for c in counts if c)
    best = cur = 0
    for c in counts:
        cur = cur + 1 if c else 0
        best = max(best, cur)
    peak_i = max(range(len(counts)), key=lambda i: counts[i]) if counts else 0
    return active, best, peak_i


def thermal_map(t, days, x0, y0):
    """Every day of the year as a cell on a heat plate, the calendar drawn as a thermal map."""
    o, css = [], []
    if not days:
        return "", "", 0
    C, G = 13, 2.6
    first = dt.date.fromisoformat(days[0]["d"])
    off = (first.weekday() + 1) % 7            # Sunday at the top, as GitHub draws it
    mx = max(d["c"] for d in days) or 1
    ops = [0.22, 0.42, 0.68, 1.0]
    ncol = (off + len(days) - 1) // 7 + 1
    gx0 = x0 + 26
    for i, d in enumerate(days):
        col, row = (off + i) // 7, (off + i) % 7
        x, y = gx0 + col * (C + G), y0 + 22 + row * (C + G)
        c = d["c"]
        if c:
            lvl = min(3, int(4 * math.log1p(c) / math.log1p(mx) - 1e-9))
            o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{C}" height="{C}" rx="2.5" fill="{t["accent"]}" fill-opacity="{ops[lvl]}" '
                     f'class="hc fb" style="animation-delay:{0.4+col*0.03:.2f}s"/>')
            if lvl == 3:
                o.append(f'<rect x="{x-2:.1f}" y="{y-2:.1f}" width="{C+4}" height="{C+4}" rx="4" fill="none" stroke="{t["accent"]}" '
                         f'stroke-opacity=".45" class="hot"/>')
        else:
            o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{C}" height="{C}" rx="2.5" fill="{t["deep"]}" stroke="{t["rule_faint"]}" stroke-width="0.8"/>')
        if d["d"][8:] == "01":
            o.append(text(x, y0 + 12, dt.date.fromisoformat(d["d"]).strftime("%b").upper(), "mono", 10.5, t["ink4"]))
    for row, lab in ((1, "MON"), (3, "WED"), (5, "FRI")):
        o.append(text(x0 + 20, y0 + 22 + row * (C + G) + 10, lab, "mono", 9, t["ink4"], "end"))
    w = ncol * (C + G)
    gh = 7 * (C + G)
    # the scanner: a warm band that passes over the plate every so often
    o.append(f'<defs><clipPath id="thc"><rect x="{gx0-2}" y="{y0+20}" width="{w+2:.1f}" height="{gh+2:.1f}"/></clipPath>'
             f'<linearGradient id="thg" x1="0" x2="1"><stop offset="0" stop-color="{t["accent"]}" stop-opacity="0"/>'
             f'<stop offset=".8" stop-color="{t["accent"]}" stop-opacity="{0.22 if t["glow_op"] > .5 else 0.14}"/>'
             f'<stop offset="1" stop-color="{t["accent"]}" stop-opacity=".9"/></linearGradient></defs>')
    o.append(f'<g clip-path="url(#thc)"><g class="thscan"><rect x="{gx0-60}" y="{y0+20}" width="60" height="{gh+2:.1f}" fill="url(#thg)"/></g></g>')
    css.append(f".thscan{{animation:thscan 9s cubic-bezier(.45,0,.55,1) 2.5s infinite backwards}}"
               f"@keyframes thscan{{0%{{transform:translateX(0);opacity:0}}5%{{opacity:1}}55%{{transform:translateX({w+60:.0f}px);opacity:1}}56%,100%{{opacity:0;transform:translateX({w+60:.0f}px)}}}}"
               ".hc{transform-origin:50% 50%;animation:hc .5s cubic-bezier(.3,1.5,.5,1) backwards}@keyframes hc{from{opacity:0;transform:scale(.2)}}"
               ".hot{animation:hot 2.4s ease-in-out infinite alternate}@keyframes hot{from{stroke-opacity:.6}to{stroke-opacity:.05}}")
    ly = y0 + 22 + gh + 18
    o.append(text(gx0, ly, "less", "mono", 10.5, t["ink4"]))
    for k, op in enumerate([0] + ops):
        fill = f'fill="{t["accent"]}" fill-opacity="{op}"' if op else f'fill="{t["deep"]}" stroke="{t["rule_faint"]}"'
        o.append(f'<rect x="{gx0+38+k*17}" y="{ly-10}" width="{C}" height="{C}" rx="2.5" {fill}/>')
    o.append(text(gx0 + 38 + 5 * 17 + 4, ly, "more", "mono", 10.5, t["ink4"]))
    o.append(text(gx0 + w, ly, "one cell per day, oldest on the left", "mono", 10.5, t["ink4"], "end"))
    return "".join(o), "".join(css), w + 26


def weekday_rose(t, days, cx, cy):
    """Contributions by weekday, drawn as the spray from an injector plate."""
    tot = [0] * 7
    for d in days:
        tot[dt.date.fromisoformat(d["d"]).weekday()] += d["c"]
    mx = max(tot) or 1
    best = tot.index(mx)
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    R0, R1 = 16, 74
    o = [f'<circle cx="{cx}" cy="{cy}" r="{R1+8}" fill="{t["deep"]}" stroke="{t["rule_strong"]}" stroke-width="1"/>']
    for k in range(24):
        a = math.radians(k * 15)
        o.append(f'<circle cx="{cx+(R1+2)*math.cos(a):.1f}" cy="{cy+(R1+2)*math.sin(a):.1f}" r="1.3" fill="none" stroke="{t["rule"]}" stroke-width="0.7"/>')
    for r_ in (R1 * 0.5, R1):
        o.append(f'<circle cx="{cx}" cy="{cy}" r="{r_:.1f}" fill="none" stroke="{t["rule_faint"]}" stroke-width="0.7" stroke-dasharray="2 3"/>')
    o.append(f'<g transform="translate({cx},{cy})">')
    span = 360 / 7
    for k, v in enumerate(tot):
        a0, a1 = math.radians(-90 + k * span + 3), math.radians(-90 + (k + 1) * span - 3)
        r = R0 + (R1 - R0) * math.sqrt(v / mx)
        d = (f"M{R0*math.cos(a0):.1f},{R0*math.sin(a0):.1f} L{r*math.cos(a0):.1f},{r*math.sin(a0):.1f} "
             f"A{r:.1f},{r:.1f} 0 0 1 {r*math.cos(a1):.1f},{r*math.sin(a1):.1f} L{R0*math.cos(a1):.1f},{R0*math.sin(a1):.1f} "
             f"A{R0},{R0} 0 0 0 {R0*math.cos(a0):.1f},{R0*math.sin(a0):.1f} Z")
        o.append(f'<path d="{d}" fill="{t["accent"]}" fill-opacity="{0.85 if k == best else 0.4}" stroke="{t["accent"]}" stroke-width="1" '
                 f'class="petal{" best" if k == best else ""}" style="animation-delay:{0.6+k*0.1:.2f}s"/>')
        am = math.radians(-90 + (k + 0.5) * span)
        lx, ly = (R1 + 22) * math.cos(am), (R1 + 22) * math.sin(am)
        anc = "middle" if abs(lx) < 20 else ("start" if lx > 0 else "end")
        o.append(text(lx, ly - 1, names[k].upper(), "mono-m", 10, t["accent"] if k == best else t["ink3"], anc))
        o.append(text(lx, ly + 12, str(v), "mono", 10, t["ink4"], anc))
    o.append(f'<circle r="{R0-4}" fill="{t["sheet"]}" stroke="{t["rule_ink"]}" stroke-width="1"/><circle r="3" fill="{t["accent"]}"/>')
    o.append("</g>")
    css = (".petal{transform-origin:0 0;animation:petal .9s cubic-bezier(.3,1.5,.5,1) backwards}@keyframes petal{from{transform:scale(0)}}"
           ".best{animation:petal .9s cubic-bezier(.3,1.5,.5,1) backwards,bestp 2.2s ease-in-out 1.6s infinite alternate}"
           "@keyframes bestp{to{fill-opacity:.5}}")
    return "".join(o), css, names[best]


def plate_telemetry(t, s, updated) -> str:
    H = 1250
    odo = Odo()
    o = sheet_frame(t, H, H - M, cols="ABCDEFGH", grid=False)
    days = s.get("days") or []
    active, streak, peak_i = day_stats(days) if days else (0, 0, 0)
    years = dt.date.today().year - int(s["active_since"])

    # ---- readouts on drums
    o.append(label(M + 22, 70, "Telemetry  ·  last 365 days", t, t["accent"], 12.5))
    o.append(text(W - M - 22, 72, f"Read from GitHub on {dt.date.fromisoformat(updated).strftime('%-d %B %Y')}.", "serif-i", 22, t["ink3"], "end"))
    o.append(rule(M + 22, 88, W - M - 22, 88, t["rule"], 0.8))
    last30 = sum(d["c"] for d in days[-30:])
    peak = days[peak_i]["c"] if days else 0
    cells = [
        (f'{s["contributions_last_year"]:,}', "contributions", "commits, PRs, reviews"),
        (f"{last30}", "last 30 days", f"{round(100*last30/max(s['contributions_last_year'],1))}% of the year's total"),
        (f"{peak}", "busiest day", dt.date.fromisoformat(days[peak_i]["d"]).strftime("%-d %B") if days else ""),
        (f'{s["repos_total"]}', "repositories", f'{s["repos_public"]} public' if s["repos_total"] != s["repos_public"] else "all public"),
        (s["active_since"], "on GitHub since", f"{years} years of flight tests"),
    ]
    cw = (W - 2 * M - 44) / len(cells)
    for i, (v, lab, sub) in enumerate(cells):
        x = M + 22 + i * cw
        if i:
            o.append(rule(x - 12, 108, x - 12, 218, t["rule_faint"], 0.8))
        o.append(label(x, 122, lab, t, t["ink4"], 11))
        sv, _ = odo.number(x, 182, v, 60, t["ink"], "serif", 0.3 + i * 0.15, 2.4, "start")
        o.append(sv)
        o.append(text(x, 210, sub, "mono", 12.5, t["ink3"]))

    # ---- the scope: a year of contributions as a burn trace
    sx0, sy0, sx1, sy1 = M + 22, 248, W - M - 22, 560
    o.append(f'<rect x="{sx0}" y="{sy0}" width="{sx1-sx0}" height="{sy1-sy0}" rx="10" fill="{t["scope"]}" stroke="{t["rule_strong"]}" stroke-width="1.2"/>')
    px0, px1, base, top = sx0 + 26, sx1 - 26, sy1 - 46, sy0 + 50
    for k in range(1, 12):
        xx = px0 + (px1 - px0) * k / 12
        o.append(rule(xx, sy0 + 12, xx, sy1 - 36, t["rule_faint"], 0.6, "2 4"))
    for k in range(1, 5):
        yy = base - (base - top) * k / 5
        o.append(rule(sx0 + 12, yy, sx1 - 12, yy, t["rule_faint"], 0.6, "2 4"))
    o.append(rule(px0, base, px1, base, t["rule"], 0.8))
    o.append(label(sx0 + 22, sy0 + 30, "burn trace  ·  contributions per day", t, t["ink3"], 11))
    o.append(text(sx1 - 22, sy0 + 30, "height is logarithmic, so quiet days still show", "mono", 11.5, t["ink4"], "end"))
    if days:
        mx = max(max(d["c"] for d in days), 1)
        n = len(days)
        step = (px1 - px0) / max(n - 1, 1)

        def Y(c):
            return base - (base - top) * math.log1p(c) / math.log1p(mx)
        pts = [(px0 + i * step, Y(d["c"])) for i, d in enumerate(days)]
        # a log axis that can be read: 1, 10, 100, ...
        v = 1
        while v <= mx:
            yy = Y(v)
            o.append(rule(px0 - 6, yy, px1, yy, t["rule"], 0.6, "1 3"))
            o.append(text(px0 - 9, yy + 4, str(v), "mono", 10, t["ink4"], "end"))
            v *= 10
        # scanlines, as on a tube (night issue)
        if t["glow_op"] > .5:
            o.append(f'<defs><pattern id="scanl" width="4" height="3" patternUnits="userSpaceOnUse"><rect width="4" height="1" fill="#ffffff" fill-opacity=".035"/></pattern></defs>'
                     f'<rect x="{sx0+2}" y="{sy0+2}" width="{sx1-sx0-4}" height="{sy1-sy0-4}" rx="9" fill="url(#scanl)"/>')
        # the sweep: a vertical beam with afterglow, in step with the trace
        o.append(f'<defs><linearGradient id="sweepG" x1="0" x2="1"><stop offset="0" stop-color="{t["phosphor"]}" stop-opacity="0"/>'
                 f'<stop offset="1" stop-color="{t["phosphor"]}" stop-opacity="{0.18 if t["glow_op"] > .5 else 0.1}"/></linearGradient>'
                 f'<clipPath id="scopeC"><rect x="{px0}" y="{sy0+8}" width="{px1-px0}" height="{sy1-sy0-16}"/></clipPath></defs>')
        # keyed to path length, the way the beam and the trace travel, so all three stay together
        acc_l = [0.0]
        for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
            acc_l.append(acc_l[-1] + math.hypot(xb - xa, yb - ya))
        idx = list(range(0, len(pts), 8)) + [len(pts) - 1]
        kt_s = [0.6 * acc_l[i] / acc_l[-1] for i in idx] + [0.64, 1.0]
        vals = [f"{pts[i][0]-px0:.1f},0" for i in idx] + [f"{px1-px0:.1f},0"] * 2
        op_anim = (f'<animate attributeName="opacity" dur="12s" repeatCount="indefinite" keyTimes="0;0.6;0.64;1" values="1;1;0;0"/>')
        o.append(f'<g clip-path="url(#scopeC)"><g><animateTransform attributeName="transform" type="translate" dur="12s" repeatCount="indefinite" '
                 f'calcMode="linear" keyTimes="{";".join(f"{v:.4f}" for v in kt_s)}" values="{";".join(vals)}"/>{op_anim}'
                 f'<rect x="{px0-90}" y="{sy0+8}" width="90" height="{base-sy0-8}" fill="url(#sweepG)"/>'
                 f'<path d="M{px0},{sy0+8} V{base}" stroke="{t["phosphor"]}" stroke-width="1" stroke-opacity=".6"/></g></g>')
        dpath = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        area = dpath + f" L{px1:.1f},{base} L{px0:.1f},{base} Z"
        o.append(f'<path d="{area}" fill="url(#burnA)" class="areaFade"/>')
        if t["glow_op"] > .5:
            o.append(f'<path d="{dpath}" pathLength="1" fill="none" stroke="{t["phosphor"]}" stroke-width="5" stroke-opacity=".25" '
                     'stroke-linejoin="round" class="trace" filter="url(#blur3)"/>')
        o.append(f'<path d="{dpath}" pathLength="1" fill="none" stroke="{t["phosphor"]}" stroke-width="1.5" stroke-linejoin="round" class="trace"/>')
        # beam head riding the trace
        o.append(f'<g class="beam"><animateMotion dur="12s" repeatCount="indefinite" keyPoints="0;1;1" keyTimes="0;0.6;1" '
                 f'calcMode="linear" path="{dpath}"/>'
                 f'<circle r="16" fill="url(#beamG)"/><circle r="3" fill="{t["fire_core"] if t["glow_op"]>.5 else t["accent"]}"/></g>')
        # month ticks
        first = dt.date.fromisoformat(days[0]["d"])
        for i, d in enumerate(days):
            dd = dt.date.fromisoformat(d["d"])
            if dd.day == 1:
                xx = px0 + i * step
                o.append(rule(xx, base, xx, base + 6, t["rule_strong"], 0.8))
                o.append(text(xx + 4, base + 22, dd.strftime("%b").upper(), "mono", 11, t["ink4"]))
        # peak annotation
        pk = days[peak_i]
        pxp, pyp = pts[peak_i]
        o.append(f'<circle cx="{pxp:.1f}" cy="{pyp:.1f}" r="5" fill="none" stroke="{t["accent"]}" stroke-width="1.4" class="fi"{d_(7.4)}/>')
        lab = f"busiest day · {pk['c']} · {dt.date.fromisoformat(pk['d']).strftime('%-d %b')}"
        tx = pxp - 14 if pxp > W / 2 else pxp + 14
        o.append(f'<g class="fi"{d_(7.5)}>' + rule(pxp, pyp - 6, pxp, sy0 + 46, t["accent_line"], 0.8, "2 3") +
                 text(tx, sy0 + 56, lab.upper(), "mono-m", 11, t["accent"], "end" if pxp > W / 2 else "start", tracking=0.12) + "</g>")
        _ = first
        # the next two brightest days, at least a week from each other and the peak
        order = sorted(range(len(days)), key=lambda i: -days[i]["c"])
        picked = [peak_i]
        for i in order:
            if len(picked) == 3:
                break
            if days[i]["c"] and all(abs(i - j) >= 7 for j in picked):
                picked.append(i)
        for rank, i in enumerate(picked[1:], start=2):
            xq, yq = pts[i]
            dlq = 7.4 + rank * 0.15
            o.append(f'<g class="fi"{d_(dlq)}><circle cx="{xq:.1f}" cy="{yq:.1f}" r="4.5" fill="none" stroke="{t["accent"]}" stroke-width="1.2"/>'
                     f'<rect x="{xq-26:.1f}" y="{yq-26:.1f}" width="15" height="15" rx="2" fill="{t["accent"]}"/>'
                     + text(xq - 18.5, yq - 14.5, str(rank), "mono-m", 10.5, t["sheet"], "middle")
                     + text(xq - 30, yq - 14.5, str(days[i]["c"]), "mono", 10.5, t["ink3"], "end") + "</g>")

    # ---- thermal map and firing pattern
    ry0 = 596
    o.append(label(M + 22, ry0, "thermal map  ·  every day of the last year", t, t["ink3"], 11))
    th_svg, th_css, th_w = thermal_map(t, days, M + 22, ry0 + 18)
    o.append(th_svg)
    rcx, rcy = W - M - 132, ry0 + 112
    o.append(label(W - M - 22, ry0, "firing pattern  ·  by weekday", t, t["ink3"], 11, "end"))
    rose_svg, rose_css, best_day = weekday_rose(t, days, rcx, rcy) if days else ("", "", "")
    o.append(rose_svg)

    # ---- propellant: languages as tanks, feeding one engine
    langs = [l for l in s["languages_by_repos"] if l["name"] != "Jupyter Notebook"][:8]
    mxr = max(l["repos"] for l in langs) if langs else 1
    ty0 = 870
    o.append(label(M + 22, ty0, "propellant  ·  languages, by repositories that use them", t, t["ink3"], 11))
    TW, TH = 50, 106
    span_x = W - M - 22 - 190 - (M + 22)
    gap = span_x / len(langs)
    ty, my = ty0 + 66, ty0 + 66 + TH + 48
    ex = W - M - 160
    tanks_css = []
    # manifold: the shared line every tank feeds
    mx0 = M + 22 + gap / 2
    o.append(f'<path d="M{mx0:.1f},{my-5} H{ex-30} M{mx0:.1f},{my+5} H{ex-30}" stroke="{t["rule_strong"]}" stroke-width="1.1"/>')
    o.append(f'<path d="M{mx0:.1f},{my} H{ex-30}" stroke="{t["accent"]}" stroke-width="3" stroke-dasharray="6 10" class="flowm"/>')
    for i, l in enumerate(langs):
        cx_ = M + 22 + i * gap + gap / 2
        x = cx_ - TW / 2
        lvl = TH * l["repos"] / mxr
        o.append(text(cx_, ty0 + 30, l["name"], "mono-m", 13, t["ink2"], "middle"))
        o.append(text(cx_, ty0 + 48, f'{l["repos"]} repo{"s" if l["repos"] != 1 else ""}', "mono", 11.5, t["ink4"], "middle"))
        cid = f"tk{i}"
        o.append(f'<defs><clipPath id="{cid}"><rect x="{x:.1f}" y="{ty}" width="{TW}" height="{TH}" rx="{TW/2}"/></clipPath></defs>')
        o.append(f'<rect x="{x:.1f}" y="{ty}" width="{TW}" height="{TH}" rx="{TW/2}" fill="{t["deep"]}" stroke="{t["rule_strong"]}" stroke-width="1.1"/>')
        wave = (f"M{x-TW:.1f},0 " + " ".join(f"q{TW/4:.1f},-5 {TW/2:.1f},0 t{TW/2:.1f},0" for _ in range(3)) + f" V{TH+20} H{x-TW:.1f} Z")
        fill = t["accent"] if i == 0 else t["ink3"]
        k = f"fill{i}"
        tanks_css.append(f"@keyframes {k}{{from{{transform:translateY({lvl:.1f}px)}}}}")
        o.append(f'<g clip-path="url(#{cid})"><g transform="translate(0,{ty+TH-lvl:.1f})">'
                 f'<g style="animation:{k} 2.2s cubic-bezier(.2,.8,.2,1) {0.6+i*0.12:.2f}s backwards">'
                 f'<g class="wave" style="animation-delay:{-i*0.4:.2f}s"><path d="{wave}" fill="{fill}" fill-opacity="{0.9 if i == 0 else 0.45}"/></g>'
                 f'</g></g></g>')
        for k2 in range(1, 4):
            yy = ty + TH * k2 / 4
            o.append(rule(x + TW - 9, yy, x + TW - 2, yy, t["rule"], 0.8))
        o.append(f'<path d="M{x+9:.1f},{ty+16} V{ty+TH-16}" stroke="#fff" stroke-opacity=".12" stroke-width="4" stroke-linecap="round"/>')
        # feed line, valve, tee into the manifold; more repos, faster flow
        fy0, vy = ty + TH, ty + TH + 22
        o.append(f'<path d="M{cx_-3:.1f},{fy0} V{my-5} M{cx_+3:.1f},{fy0} V{my-5}" stroke="{t["rule_strong"]}" stroke-width="0.9"/>')
        o.append(f'<path d="M{cx_:.1f},{fy0} V{my}" stroke="{fill}" stroke-width="2" stroke-dasharray="3 6" '
                 f'class="flowf" style="animation-duration:{2.2-1.5*l["repos"]/mxr:.2f}s"/>')
        o.append(f'<path d="M{cx_-8:.1f},{vy-6} L{cx_+8:.1f},{vy+6} V{vy-6} L{cx_-8:.1f},{vy+6} Z" fill="{t["sheet"]}" stroke="{t["rule_ink"]}" stroke-width="1"/>')
        o.append(f'<circle cx="{cx_:.1f}" cy="{my}" r="3.2" fill="{t["sheet"]}" stroke="{t["rule_ink"]}" stroke-width="1"/>')
    # the engine all of it feeds
    o.append(f'<g transform="translate({ex},{my})">'
             f'<path d="M-30,-14 H30 V14 H-30 Z" fill="{t["raised"]}" stroke="{t["rule_ink"]}" stroke-width="1.2"/>'
             f'<path d="M-30,-14 Q0,-34 30,-14" fill="none" stroke="{t["rule_ink"]}" stroke-width="1.2"/>'
             f'<path d="M-16,14 Q-16,24 -6,30 Q-22,46 -28,66 H28 Q22,46 6,30 Q16,24 16,14" fill="{t["sheet"]}" stroke="{t["rule_ink"]}" stroke-width="1.2"/>'
             f'<g class="fb fl2" style="transform-origin:50% 0"><path d="M-26,66 C-30,84 -12,104 0,118 C12,104 30,84 26,66 Z" fill="{t["fire_mid"]}" fill-opacity=".75"/></g>'
             f'<g class="fb fl3" style="transform-origin:50% 0"><path d="M-14,66 C-14,78 -6,92 0,100 C6,92 14,78 14,66 Z" fill="{t["fire_core"]}" fill-opacity=".95"/></g>'
             + label(46, -24, "one engine", t, t["accent"], 10.5) + text(46, -8, "every language", "mono", 10.5, t["ink4"])
             + text(46, 6, "feeds the same", "mono", 10.5, t["ink4"]) + text(46, 20, "build", "mono", 10.5, t["ink4"]) + "</g>")

    defs = ('<defs>'
            f'<linearGradient id="burnA" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t["phosphor"]}" stop-opacity="{0.32 if t["glow_op"]>.5 else 0.18}"/>'
            f'<stop offset="1" stop-color="{t["phosphor"]}" stop-opacity="0"/></linearGradient>'
            f'<radialGradient id="beamG"><stop offset="0" stop-color="{t["phosphor"]}" stop-opacity=".9"/><stop offset="1" stop-color="{t["phosphor"]}" stop-opacity="0"/></radialGradient>'
            '<filter id="blur3" x="-5%" y="-20%" width="110%" height="140%"><feGaussianBlur stdDeviation="3"/></filter>'
            '</defs>')
    css = (odo.css() + "".join(tanks_css) + th_css + rose_css +
           ".flowm{animation:flowm .9s linear infinite}@keyframes flowm{to{stroke-dashoffset:-16}}"
           ".flowf{animation:flowf 1.4s linear infinite}@keyframes flowf{to{stroke-dashoffset:-9}}"
           ".fl2{animation:fl .23s ease-in-out infinite alternate-reverse}.fl3{animation:fl .17s ease-in-out infinite alternate}"
           "@keyframes fl{from{transform:scale(1,1)}to{transform:scale(.95,1.1)}}" +
           ".trace{stroke-dasharray:1 1;animation:trace 12s linear infinite}"
           "@keyframes trace{0%{stroke-dashoffset:1;opacity:1}60%{stroke-dashoffset:0;opacity:1}92%{stroke-dashoffset:0;opacity:1}100%{stroke-dashoffset:0;opacity:0}}"
           ".areaFade{animation:areaF 12s linear infinite}"

           "@keyframes areaF{0%,30%{opacity:0}60%,92%{opacity:1}100%{opacity:0}}"
           ".wave{animation:wave 2.6s linear infinite}"
           f"@keyframes wave{{to{{transform:translateX({TW}px)}}}}")
    alt = (f"Telemetry. {s['contributions_last_year']} contributions in the last year across {s['repos_total']} repositories; "
           f"{active} active days; longest run {streak} days; on GitHub since {s['active_since']}. "
           "A year of daily contributions drawn as an oscilloscope trace, and languages drawn as propellant tanks filled by how many repositories use them.")
    return svg(W, H, defs + "\n".join(o), ("serif", "serif-i", "mono", "mono-m"), alt, css)


# --------------------------------------------------------------------------
# Plate 6: the closing sheet. The same engine, on a vehicle, flying the work.
# --------------------------------------------------------------------------
def _bez(p0, p1, p2, p3, u):
    a = (1 - u) ** 3
    b = 3 * (1 - u) ** 2 * u
    c = 3 * (1 - u) * u ** 2
    d = u ** 3
    return (a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1])


def _arc_samples(segs, n=400):
    """Points along a chain of cubics, with the arc length fraction at each."""
    pts = []
    for s in segs:
        for i in range(n + 1):
            if pts and i == 0:
                continue
            pts.append(_bez(*s, i / n))
    acc = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        acc.append(acc[-1] + math.hypot(x1 - x0, y1 - y0))
    return pts, [a / acc[-1] for a in acc]


def _at(pts, fr, s):
    for i, f in enumerate(fr):
        if f >= s:
            return pts[i]
    return pts[-1]


def stage_art(t, upper: bool):
    """A stage in elevation, lying along +x (the direction of flight)."""
    ink, strong = t["rule_ink"], t["rule_strong"]
    if upper:
        return (f'<path d="M0,-9 H54 C66,-9 76,-4 82,0 C76,4 66,9 54,9 H0 Z" fill="{t["sheet"]}" stroke="{ink}" stroke-width="1.3"/>'
                f'<path d="M30,-9 V9 M54,-9 V9" stroke="{strong}" stroke-width="0.8"/>'
                f'<path d="M0,-5 L-7,-7 V7 L0,5 Z" fill="{t["sunk"]}" stroke="{ink}" stroke-width="1"/>'
                + text(18, 3, "GH-01", "mono-m", 6.5, t["accent"], "middle"))
    return (f'<path d="M-62,-9 H0 V9 H-62 Z" fill="{t["sheet"]}" stroke="{ink}" stroke-width="1.3"/>'
            f'<path d="M-40,-9 V9 M-20,-9 V9" stroke="{strong}" stroke-width="0.8"/>'
            f'<path d="M-50,-9 L-66,-21 H-72 L-62,-9 Z M-50,9 L-66,21 H-72 L-62,9 Z" fill="{t["raised"]}" stroke="{ink}" stroke-width="1.1"/>'
            f'<path d="M-62,-6 L-71,-8 V8 L-62,6 Z" fill="{t["sunk"]}" stroke="{ink}" stroke-width="1"/>')


def plume_art(t, x, length, width):
    return (f'<g transform="translate({x},0)"><path d="M0,{-width} C{-length*0.3},{-width*1.3} {-length*0.7},{-width*0.5} {-length},0 '
            f'C{-length*0.7},{width*0.5} {-length*0.3},{width*1.3} 0,{width} Z" fill="url(#plh)" class="fb flx"/>'
            f'<path d="M0,{-width*0.5} C{-length*0.2},{-width*0.6} {-length*0.4},{-width*0.2} {-length*0.5},0 '
            f'C{-length*0.4},{width*0.2} {-length*0.2},{width*0.6} 0,{width*0.5} Z" fill="{t["fire_core"]}" fill-opacity=".95" class="fb flx2"/></g>')


def plate_closing(t, updated, rev) -> str:
    H = 660
    TBY = H - M - 62
    GY = TBY - 52          # ground
    CYC = 16.0
    T_IGN, T_LIFT, T_END, T_HOLD, T_RESET = 0.18, 0.20, 0.72, 0.86, 0.885
    odo = Odo()
    o = sheet_frame(t, H, TBY, cols="ABCDEFGHJK")

    # ---- the flight path: up off the pad, over, and out to orbit
    # the anchor is the joint between the stages, one stage length above the pad
    P0, P1, P2, P3 = (760, GY - 84), (760, GY - 210), (820, GY - 320), (960, GY - 372)
    P4, P5, P6 = (2 * P3[0] - P2[0], 2 * P3[1] - P2[1]), (1160, GY - 440), (1260, GY - 456)
    segs = [(P0, P1, P2, P3), (P3, P4, P5, P6)]
    dpath = f"M{P0[0]},{P0[1]} C{P1[0]},{P1[1]} {P2[0]},{P2[1]} {P3[0]},{P3[1]} C{P4[0]},{P4[1]} {P5[0]},{P5[1]} {P6[0]},{P6[1]}"
    pts, fr = _arc_samples(segs)
    POW = 1.75                      # thrust accelerates the climb

    def t_at(s):
        return T_LIFT + (T_END - T_LIFT) * s ** (1 / POW)
    us = [i / 14 for i in range(15)]
    kt = [0.0, T_LIFT] + [T_LIFT + (T_END - T_LIFT) * u for u in us[1:]] + [T_RESET - 0.002, T_RESET, 1.0]
    kp = [0.0, 0.0] + [u ** POW for u in us[1:]] + [1.0, 0.0, 0.0]
    KT = ";".join(f"{v:.4f}" for v in kt)
    KP = ";".join(f"{v:.4f}" for v in kp)
    S_SEP = 0.42
    t_sep = t_at(S_SEP)
    kp_low = [min(v, S_SEP) for v in kp]

    defs = (f'<defs><clipPath id="sky"><rect x="{M}" y="{M}" width="{W-2*M}" height="{TBY-M}"/></clipPath>'
            f'<linearGradient id="plh" x1="1" x2="0"><stop offset="0" stop-color="{t["fire_core"]}"/>'
            f'<stop offset=".3" stop-color="{t["fire_mid"]}" stop-opacity=".95"/><stop offset="1" stop-color="{t["fire_outer"]}" stop-opacity="0"/></linearGradient>'
            f'<radialGradient id="smk"><stop offset="0" stop-color="{t["smoke"]}" stop-opacity=".55"/>'
            f'<stop offset=".7" stop-color="{t["smoke"]}" stop-opacity=".2"/><stop offset="1" stop-color="{t["smoke"]}" stop-opacity="0"/></radialGradient>'
            f'<radialGradient id="padG"><stop offset="0" stop-color="{t["fire_mid"]}" stop-opacity="{0.6*t["glow_op"]+0.1:.2f}"/>'
            f'<stop offset="1" stop-color="{t["fire_mid"]}" stop-opacity="0"/></radialGradient>'
            f'<filter id="tglow" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="3"/></filter></defs>')
    o.append(defs)

    # ---- words
    o.append(label(70, 106, "Sheet GH-01  ·  end of set", t, t["accent"], 12.5, extra=f' class="mono-m lt"{d_(0.1)}'))
    o.append(f'<g class="up"{d_(0.2)}>' + text(64, 196, "In thrust", "serif-i", 92, t["accent"]) + "</g>")
    o.append(f'<g class="up"{d_(0.35)}>' + text(64, 286, "we trust.", "serif-i", 92, t["accent"]) + "</g>")
    o.append(f'<g class="up"{d_(0.5)}>' + text(70, 340, "Reliability is a feature. So is honesty", "sans", 22, t["ink2"])
             + text(70, 370, "about what isn't done yet.", "sans", 22, t["ink2"]) + "</g>")
    o.append(line_pen(70, 404, 250, 404, t["rule_strong"], 1, 0.7, 0.8))
    o.append(label(70, 436, "akshaybajpai.com", t, t["ink2"], 12.5, extra=f' class="mono-m fi"{d_(0.9)}'))
    o.append(label(70, 460, "contact@akshaybajpai.com", t, t["ink2"], 12.5, extra=f' class="mono-m fi"{d_(1.0)}'))

    o.append('<g clip-path="url(#sky)">')
    # stars come out as it climbs (night issue only)
    if t["glow_op"] > .5:
        rnd = random.Random(5)
        for _ in range(70):
            x, y = rnd.uniform(560, W - M), rnd.uniform(M, GY - 120)
            o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rnd.uniform(.5, 1.3):.1f}" fill="#e6f1fc" class="tw" '
                     f'style="animation-delay:{-rnd.uniform(0, 4):.2f}s;animation-duration:{rnd.uniform(2.5, 5):.2f}s"/>')
    # ground, pad, tower
    o.append(f'<rect x="540" y="{GY}" width="{W-M-540}" height="14" fill="url(#gM)"/>')
    o.append(rule(540, GY, W - M, GY, t["rule_strong"], 1.2))
    for k in range(32):
        xx = 548 + k * 19
        o.append(rule(xx, GY, xx - 8, GY + 9, t["rule"], 0.7))
    px = P0[0]
    o.append(f'<path d="M{px-64},{GY} V{GY-10} H{px-22} L{px-12},{GY-2} H{px+12} L{px+22},{GY-10} H{px+64} V{GY}" fill="{t["sunk"]}" stroke="{t["rule_ink"]}" stroke-width="1.2"/>')
    tx = px - 52
    o.append(f'<path d="M{tx-10},{GY-10} V{GY-170} M{tx+10},{GY-10} V{GY-170}" stroke="{t["rule_ink"]}" stroke-width="1.1"/>')
    for k in range(8):
        y1 = GY - 10 - k * 20
        o.append(f'<path d="M{tx-10},{y1} L{tx+10},{y1-20} M{tx+10},{y1} L{tx-10},{y1-20} M{tx-10},{y1-20} H{tx+10}" stroke="{t["rule"]}" stroke-width="0.7"/>')
    o.append(f'<g transform="translate({tx+10},{GY-120})"><g class="arm"><path d="M0,0 H30 V6 H0 Z" fill="{t["raised"]}" stroke="{t["rule_ink"]}" stroke-width="1"/></g></g>')
    o.append(f'<ellipse cx="{px}" cy="{GY-6}" rx="150" ry="36" fill="url(#padG)" class="padglow"/>')
    # the trajectory as planned, and the trail as flown
    o.append(f'<path d="{dpath}" fill="none" stroke="{t["rule"]}" stroke-width="0.9" stroke-dasharray="3 5"/>')
    trail_anim = (f'<animate attributeName="stroke-dashoffset" dur="{CYC}s" repeatCount="indefinite" calcMode="linear" '
                  f'keyTimes="{KT}" values="{";".join(f"{1-v:.4f}" for v in kp)}"/>'
                  f'<animate attributeName="opacity" dur="{CYC}s" repeatCount="indefinite" keyTimes="0;{T_HOLD};{T_RESET-0.01};1" values="1;1;0;0"/>')
    if t["glow_op"] > .5:
        o.append(f'<path d="{dpath}" pathLength="1" fill="none" stroke="{t["fire_mid"]}" stroke-width="6" stroke-opacity=".35" '
                 f'stroke-dasharray="1 1" stroke-dashoffset="1" filter="url(#tglow)">{trail_anim}</path>')
    o.append(f'<path d="{dpath}" pathLength="1" fill="none" stroke="{t["accent"]}" stroke-width="2" stroke-dasharray="1 1" stroke-dashoffset="1">{trail_anim}</path>')
    # smoke rolling out along the ground at ignition
    rnd = random.Random(11)
    for k in range(16):
        side = -1 if k % 2 else 1
        dx = side * rnd.uniform(50, 230)
        dy = -rnd.uniform(4, 60)
        r = rnd.uniform(18, 38)
        o.append(f'<circle cx="{px + side*rnd.uniform(0, 26):.1f}" cy="{GY-14:.1f}" r="{r:.1f}" fill="url(#smk)" class="smoke fb" '
                 f'style="--dx:{dx:.1f}px;--dy:{dy:.1f}px;animation-delay:{rnd.uniform(0, 0.6):.2f}s"/>')
    # the lower stage: flies to staging, then falls away behind
    low_motion = (f'<animateMotion dur="{CYC}s" repeatCount="indefinite" rotate="auto" calcMode="linear" keyTimes="{KT}" '
                  f'keyPoints="{";".join(f"{v:.4f}" for v in kp_low)}" path="{dpath}"/>')
    ts1, ts2 = t_sep, min(t_sep + 0.14, T_RESET - 0.01)
    o.append(f'<g>{low_motion}<g>'
             f'<animateTransform attributeName="transform" type="translate" dur="{CYC}s" repeatCount="indefinite" '
             f'keyTimes="0;{ts1:.4f};{ts2:.4f};{T_RESET:.4f};1" values="0,0;0,0;-150,46;0,0;0,0"/>'
             f'<animateTransform attributeName="transform" type="rotate" additive="sum" dur="{CYC}s" repeatCount="indefinite" '
             f'keyTimes="0;{ts1:.4f};{ts2:.4f};{T_RESET:.4f};1" values="0;0;-70;0;0"/>'
             f'<animate attributeName="opacity" dur="{CYC}s" repeatCount="indefinite" keyTimes="0;{ts1:.4f};{ts2:.4f};{T_RESET:.4f};0.92;1" values="1;1;0;0;0;1"/>'
             f'<g opacity="0"><animate attributeName="opacity" dur="{CYC}s" repeatCount="indefinite" '
             f'keyTimes="0;{T_IGN:.4f};{ts1:.4f};1" values="0;1;0;0" calcMode="discrete"/>{plume_art(t, -71, 120, 9)}</g>'
             f'{stage_art(t, False)}</g></g>')
    # the upper stage: relights at staging and goes on to orbit
    up_motion = (f'<animateMotion dur="{CYC}s" repeatCount="indefinite" rotate="auto" calcMode="linear" keyTimes="{KT}" '
                 f'keyPoints="{KP}" path="{dpath}"/>')
    o.append(f'<g>{up_motion}<g>'
             f'<animate attributeName="opacity" dur="{CYC}s" repeatCount="indefinite" keyTimes="0;{T_END+0.01:.4f};{T_END+0.02:.4f};0.92;1" values="1;1;0;0;1"/>'
             f'<g opacity="0"><animate attributeName="opacity" dur="{CYC}s" repeatCount="indefinite" '
             f'keyTimes="0;{ts1+0.01:.4f};{T_END:.4f};1" values="0;1;0;0" calcMode="discrete"/>{plume_art(t, -7, 90, 6)}</g>'
             f'{stage_art(t, True)}</g></g>')
    # vapour venting while it waits
    for k in range(4):
        o.append(f'<circle cx="{px+12}" cy="{GY-90}" r="6" fill="url(#smk)" class="vent fb" style="animation-delay:{k*0.7:.2f}s"/>')
    # countdown, by the tower
    for k, n_ in enumerate((3, 2, 1)):
        a = 0.08 + k * 0.033
        o.append(f'<g class="cd" style="animation-delay:{a*CYC:.2f}s">' + text(tx - 30, GY - 130, f"T-{n_}", "mono-m", 22, t["accent"], "end") + "</g>")
    o.append("</g>")

    # ---- events along the way, each one a stage of the work
    events = [(0.0, "liftoff", "first client call"), (0.2, "max-q", "scope and sign-off"),
              (S_SEP, "staging", "the build"), (0.6, "fairing sep", "the release"), (0.77, "orbit", "the runbook after")]
    css_ev = []
    for k, (s_, ev, work) in enumerate(events):
        ex, ey = _at(pts, fr, s_)
        te = t_at(s_)
        name = f"ev{k}"
        css_ev.append(f"@keyframes {name}{{0%,{te*100-0.1:.2f}%{{opacity:0;transform:scale(.4)}}{te*100+1.5:.2f}%{{opacity:1;transform:scale(1.15)}}"
                      f"{te*100+3:.2f}%,{T_HOLD*100:.2f}%{{opacity:1;transform:scale(1)}}{(T_RESET)*100:.2f}%,100%{{opacity:0;transform:scale(1)}}}}")
        if ex > 960:
            lx, ly, anc = ex - 14, ey - 26, "end"
        else:
            lx, ly, anc = ex + 18, ey + 5, "start"
        o.append(f'<g class="ev" style="animation-name:{name}"><g>'
                 f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="5" fill="{t["sheet"]}" stroke="{t["accent"]}" stroke-width="1.6"/>'
                 f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="2" fill="{t["accent"]}"/>'
                 + label(lx, ly, ev, t, t["accent"], 11.5, anc)
                 + text(lx, ly + 17, work, "mono", 12, t["ink2"], anc) + "</g></g>")

    # ---- title block, with a live clock and the flight's status
    cells = [("end of set", "GH-01 of 01", 190), ("rev", str(rev), 90), ("mission time", "", 200),
             ("status", "", 220), ("last updated", updated, W - 2 * M - 700)]
    o += title_block(t, TBY, cells)
    cx_ = M + 190 + 90
    o.append(text(cx_ + 14, TBY + 48, "T+", "mono-m", 15, t["ink3"]) + odo.clock(cx_ + 40, TBY + 48, 15, t["ink"], 0.0))
    sx = cx_ + 200 + 14
    status = [(0.0, T_IGN, "hold"), (T_IGN, T_LIFT, "ignition")]
    times = [t_at(s_) for s_, _, _ in events]
    for k, (s_, ev, _) in enumerate(events):
        end = times[k + 1] if k + 1 < len(events) else T_RESET
        status.append((times[k], end, ev))
    status.append((T_RESET, 1.0, "hold"))
    for k, (a, b, lab_) in enumerate(status):
        css_ev.append(f"@keyframes st{k}{{0%{{opacity:0}}{a*100:.2f}%{{opacity:1}}{b*100:.2f}%,100%{{opacity:0}}}}")
        col = t["accent"] if lab_ not in ("hold",) else t["ink2"]
        o.append(f'<g class="stt" style="animation-name:st{k}">' + text(sx, TBY + 48, lab_.upper(), "mono-m", 15, col, tracking=0.08) + "</g>")

    css = (FIRE_CSS + odo.css() + "".join(css_ev) +
           f".ev{{opacity:0;transform-box:fill-box;transform-origin:50% 50%;animation-duration:{CYC}s;animation-iteration-count:infinite;animation-timing-function:ease-out}}"
           f".stt{{opacity:0;animation-duration:{CYC}s;animation-iteration-count:infinite;animation-timing-function:steps(1,end)}}"
           ".flx{transform-origin:100% 50%;animation:flx .2s ease-in-out infinite alternate}"
           ".flx2{transform-origin:100% 50%;animation:flx .14s ease-in-out infinite alternate-reverse}"
           "@keyframes flx{from{transform:scale(1,1)}to{transform:scale(1.12,.92)}}"
           ".tw{animation:tw 4s ease-in-out infinite}@keyframes tw{0%,100%{opacity:.9}50%{opacity:.15}}"
           f".smoke{{opacity:0;transform-origin:50% 50%;animation:smoke {CYC}s ease-out infinite}}"
           f"@keyframes smoke{{0%,{T_IGN*100-1:.1f}%{{opacity:0;transform:translate(0,0) scale(.3)}}{T_LIFT*100+3:.1f}%{{opacity:1}}"
           f"{T_LIFT*100+22:.1f}%{{opacity:.8;transform:translate(var(--dx),var(--dy)) scale(1.9)}}"
           f"{T_HOLD*100:.1f}%,100%{{opacity:0;transform:translate(calc(var(--dx)*1.3),calc(var(--dy) - 30px)) scale(2.5)}}}}"
           f".padglow{{opacity:0;animation:padg {CYC}s ease-out infinite}}"
           f"@keyframes padg{{0%,{T_IGN*100-1:.1f}%{{opacity:0}}{T_LIFT*100:.1f}%{{opacity:1}}{T_LIFT*100+10:.1f}%{{opacity:.6}}{T_LIFT*100+22:.1f}%,100%{{opacity:0}}}}"
           f".arm{{animation:arm {CYC}s ease-in-out infinite}}"
           f"@keyframes arm{{0%,{T_IGN*100-6:.1f}%{{transform:rotate(0)}}{T_IGN*100:.1f}%,{T_RESET*100:.1f}%{{transform:rotate(-75deg)}}96%,100%{{transform:rotate(0)}}}}"
           f".vent{{opacity:0;animation:vent {CYC}s ease-out infinite}}"
           "@keyframes vent{0%{opacity:0;transform:translate(0,0) scale(.5)}2%{opacity:.8}14%{opacity:0;transform:translate(40px,-24px) scale(2.6)}100%{opacity:0}}"
           f".cd{{opacity:0;animation:cd {CYC}s steps(1) infinite}}@keyframes cd{{0%{{opacity:1}}3%,100%{{opacity:0}}}}"
           "@media (prefers-reduced-motion:reduce){.smoke,.padglow,.cd{display:none}.ev{opacity:1}.stt{display:none}}")
    alt = (f"End of set. In thrust we trust. Reliability is a feature. So is honesty about what isn't done yet. "
           "A launch, drawn as an engagement: a countdown, then liftoff at the first client call, max-Q at scope and sign-off, "
           "staging at the build, fairing separation at the release, and orbit with the runbook after. "
           f"Last updated {updated}.")
    return svg(W, H, "\n".join(o), ("serif-i", "mono", "mono-m", "sans"), alt, css)


# --------------------------------------------------------------------------
# Stats: refreshed from GitHub when a token is present, else the snapshot.
# --------------------------------------------------------------------------
QUERY = """
query($login:String!){ user(login:$login){
  createdAt
  repositories(first:100, ownerAffiliations:OWNER){ totalCount nodes{ isPrivate isFork
    languages(first:12, orderBy:{field:SIZE, direction:DESC}){ edges{ size node{ name } } } } }
  contributionsCollection{ contributionCalendar{ totalContributions
    weeks{ contributionDays{ date contributionCount } } } }
}}"""


def refresh_stats(login="ax5hay"):
    token = os.environ.get("GITHUB_TOKEN")
    path = DATA / "stats.json"
    old = json.loads(path.read_text())
    if not token:
        return old
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "ax5hay-profile-render"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            u = json.load(r)["data"]["user"]
    except Exception as e:  # keep the last good issue rather than a blank plate
        print(f"stats refresh failed, keeping snapshot: {e}")
        return old
    repos = u["repositories"]["nodes"]
    from collections import Counter
    cnt = Counter()
    for n in repos:
        edges = n["languages"]["edges"]
        tot = sum(e["size"] for e in edges) or 1
        for e in edges:
            if e["size"] / tot >= 0.05:
                cnt[e["node"]["name"]] += 1
    cal = u["contributionsCollection"]["contributionCalendar"]
    days = [{"d": d["date"], "c": d["contributionCount"]} for w in cal["weeks"] for d in w["contributionDays"]][-365:]
    weeks = [sum(d["contributionCount"] for d in w["contributionDays"]) for w in cal["weeks"]][-52:]
    s = {
        "generated": dt.date.today().isoformat(),
        "repos_total": u["repositories"]["totalCount"],
        "repos_public": sum(1 for n in repos if not n["isPrivate"]),
        "contributions_last_year": cal["totalContributions"],
        "active_since": u["createdAt"][:4],
        "languages_by_repos": [{"name": k, "repos": v} for k, v in cnt.most_common(12)],
        "weeks": weeks,
        "days": days,
    }
    # A token that cannot see private work would shrink the record overnight;
    # keep the fuller snapshot's counts instead.
    if s["repos_total"] < old.get("repos_total", 0) and s["repos_total"] == s["repos_public"]:
        print("token sees public repositories only; keeping the fuller snapshot for counts")
        for k in ("repos_total", "repos_public", "languages_by_repos"):
            s[k] = old[k]
    path.write_text(json.dumps(s, indent=1) + "\n")
    return s


def sync_readme(stack, updated, zones, notes) -> None:
    """Keep the plain-text schedule and the dateline inside README.md in step."""
    readme = ROOT / "README.md"
    if not readme.exists():
        return
    body = readme.read_text()

    def replace_block(body, start, end, inner):
        if start not in body or end not in body:
            return body
        head, rest = body.split(start, 1)
        _, tail = rest.split(end, 1)
        return head + start + inner + end + tail

    lines = [f"- **{cat['category']}.** " + ", ".join(i["name"] for i in cat["items"]) for cat in stack]
    body = replace_block(body, "<!-- schedule:start -->", "<!-- schedule:end -->", "\n" + "\n".join(lines) + "\n")
    body = replace_block(body, "<!-- index:start -->", "<!-- index:end -->", index_markdown(zones))
    body = replace_block(body, "<!-- notes:start -->", "<!-- notes:end -->", notes_markdown(notes))
    pretty = dt.date.fromisoformat(updated).strftime("%-d %B %Y")
    body = replace_block(body, "<!-- updated:start -->", "<!-- updated:end -->", pretty)
    readme.write_text(body)


def revision() -> int:
    try:
        return int(subprocess.check_output(["git", "rev-list", "--count", "HEAD"], cwd=ROOT, text=True).strip())
    except Exception:
        return 0


def main():
    stack = json.loads((DATA / "stack.json").read_text())
    zones = json.loads((DATA / "projects.json").read_text())["zones"]
    notes = json.loads((DATA / "notes.json").read_text())["notes"]
    stats = refresh_stats()
    updated = stats.get("generated") or dt.date.today().isoformat()
    rev = revision() + 1  # this render lands in the next commit
    n_materials = sum(len(c["items"]) for c in stack)
    headers = [
        ("notes", "GN", "General notes", "read before the drawings", "01 / 06"),
        ("record", "RW", "Record of work", "what was built, and what it changed", "02 / 06"),
        ("keyplan", "KP", "Key plan", "sheets filed by domain", "03 / 06"),
        ("index", "SI", "Sheet index", "numbered like the site", "04 / 06"),
        ("schedule", "SM", "Schedule of materials", "every tool, from every repo", "05 / 06"),
        ("numbers", "TM", "Telemetry", "counts, never grades", "06 / 06"),
    ]
    for theme, t in THEMES.items():
        out = ASSETS / theme
        out.mkdir(parents=True, exist_ok=True)
        (out / "hero.svg").write_text(plate_hero(t, stats, updated, rev, n_materials))
        (out / "teststand.svg").write_text(plate_teststand(t))
        (out / "notes.svg").write_text(plate_notes(t, notes, updated, rev))
        (out / "keyplan.svg").write_text(plate_keyplan(t, zones))
        (out / "schedule.svg").write_text(plate_schedule(t, stack, zones))
        (out / "numbers.svg").write_text(plate_telemetry(t, stats, updated))
        cards = out / "cards"
        cards.mkdir(exist_ok=True)
        for z in zones:
            (cards / f"zone-{z['code'].lower()}.svg").write_text(zone_band(t, z))
            for i, p in enumerate(z["projects"]):
                seed = sum(map(ord, p["name"]))
                (cards / f"{z['code'].lower()}-{i+1:02d}.svg").write_text(card(t, z, i, p, seed))
        (out / "closing.svg").write_text(plate_closing(t, updated, rev))
        for key, code, title, note, seq in headers:
            (out / f"h-{key}.svg").write_text(plate_header(t, code, title, note, seq))
    sync_readme(stack, updated, zones, notes)
    print(f"updated {updated} rev {rev}: {len(list(ASSETS.glob('*/**/*.svg')))} plates")


if __name__ == "__main__":
    main()
