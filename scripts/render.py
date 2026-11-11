#!/usr/bin/env python3
"""Render the profile README's plates as animated SVG, in a light and a dark issue.

Every image in the README is drawn here from data/*.json, in the site's own
type (Instrument Serif, IBM Plex Mono, IBM Plex Sans), embedded so GitHub's
image proxy shows it the same everywhere. Motion is CSS and SMIL inside the
SVG: no scripts, no GIFs, no third-party cards. Every animated element rests
in its final state, so `prefers-reduced-motion` shows a finished drawing.

    python scripts/render.py                    # re-issue every plate
    GITHUB_TOKEN=... python scripts/render.py   # also refresh data/stats.json

Standard library only.
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
        glow_op=0.35, smoke="#c9bfa9", phosphor="#983729", scope="#f1ece0",
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
        glow_op=1.0, smoke="#9dbdd9", phosphor="#ffc75a", scope="#020c17",
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
    ".dr{stroke-dasharray:1 1;animation:dr 1.6s cubic-bezier(.65,0,.25,1) both}"
    "@keyframes dr{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}"
    ".fi{animation:fi 1s ease-out both}"
    "@keyframes fi{from{opacity:0}}"
    ".up{animation:up 1s cubic-bezier(.2,.7,.2,1) both}"
    "@keyframes up{from{opacity:0;transform:translateY(16px)}}"
    ".lt{animation:lt 1s cubic-bezier(.2,.7,.2,1) both}"
    "@keyframes lt{from{opacity:0;transform:translateX(-14px)}}"
    ".fb{transform-box:fill-box}"
)
REDUCED = "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"


def font_faces(*keys: str) -> str:
    out = []
    for k in keys:
        name, style = FONT_FILES[k]
        b64 = base64.b64encode((ASSETS / "fonts" / name).read_bytes()).decode()
        out.append(
            f'@font-face{{font-family:"ax-{k}";font-style:{style};font-weight:400;'
            f'src:url(data:font/woff2;base64,{b64}) format("woff2");}}'
        )
    return "".join(out)


def mono_w(s: str, size: float, tracking: float = 0.0) -> float:
    return len(s) * size * (MONO_ADVANCE + tracking)


def svg(width, height, body, fonts, title, css="") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="t">\n'
        f'<title id="t">{escape(title)}</title>\n'
        f"<style>{font_faces(*fonts)}{BASE_CSS}{css}{REDUCED}</style>\n"
        f"{body}\n</svg>\n"
    )


def d_(delay: float, dur: float | None = None) -> str:
    """Inline animation timing."""
    s = f"animation-delay:{delay:.2f}s"
    if dur is not None:
        s += f";animation-duration:{dur:.2f}s"
    return f' style="{s}"'


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


STAMP_CSS = (".stamp{animation:stamp .5s cubic-bezier(.3,1.6,.5,1) both}"
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
                stack = "".join(text(cx + w / 2, y + i * L, str(i % 10), cls, size, fill, "middle")
                                for i in range(spins + 1))
                o.append(f'<g transform="translate(0,{-spins*L:.1f})"><g style="animation:{k} {dur+digit_i*0.25:.2f}s '
                         f'cubic-bezier(.2,.75,.25,1) {delay:.2f}s both">{stack}</g></g>')
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
                stack = "".join(text(cx + cw / 2, y + i * L, str(i), cls, size, fill, "middle") for i in range(n))
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
    ".ign{animation:ign 1.1s cubic-bezier(.2,.9,.2,1) both}"
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
    ".ring{transform-origin:50% 50%;animation:ring 3.6s cubic-bezier(.1,.6,.3,1) infinite both}"
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
    H = 780
    TBY = H - M - 66
    odo = Odo()
    o = sheet_frame(t, H, TBY)

    # the plotter carriage crosses the sheet once, laying the drawing down
    o.append(f'<g class="carriage"><path d="M0,{M} V{TBY}" stroke="{t["accent"]}" stroke-width="1" stroke-opacity=".7"/>'
             f'<rect x="-7" y="{M-2}" width="14" height="10" fill="{t["accent"]}"/>'
             f'<rect x="-5" y="{TBY-8}" width="10" height="8" fill="{t["accent"]}"/></g>')

    # ---- left field: the name and the thesis
    o.append(label(70, 112, "Sheet GH-01  ·  GitHub profile", t, t["accent"], 13, extra=f' class="mono-m lt"{d_(0.2)}'))
    o.append(f'<g class="up"{d_(0.35)}>' + text(62, 214, "Akshay Bajpai", "serif", 122, t["ink"]) + "</g>")
    o.append(f'<g class="up"{d_(0.6)}>' + text(68, 278, "In thrust we trust.", "serif-i", 50, t["accent"]) + "</g>")
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
    o.append(f'<g clip-path="url(#plume)"><g transform="{loc}">{engine_fire(t, ign)}</g></g>')
    o.append(f'<g transform="{loc}">{engine_glow(t, ign)}{engine_lines(t)}</g>')
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
    o.append(stamp(W - 170, TBY - 46, "last updated", updated, t, -6, 3.3))

    css = (odo.css() + FIRE_CSS + STAMP_CSS +
           ".carriage{animation:carriage 2.6s cubic-bezier(.45,0,.35,1) .1s both}"
           f"@keyframes carriage{{0%{{transform:translateX({M}px);opacity:1}}92%{{opacity:1}}100%{{transform:translateX({W-M}px);opacity:0}}}}"
           ".carriage{opacity:0}"
           ".spin{animation:spin 24s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}"
           ".flow{animation:flow 1.2s linear infinite}@keyframes flow{to{stroke-dashoffset:-11}}")
    alt = ("Akshay Bajpai. In thrust we trust. I lead technology from the first client conversation to the release: "
           "the architecture, the team, the code, and the runbook after. Boardroom to bare metal. "
           "A rocket engine is drawn by a plotter and lit; an x-ray lens drifts over it and shows the software inside.")
    return svg(W, H, "\n".join(o), ("serif", "serif-i", "mono", "mono-m", "sans"), alt, css)


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
    css = ".wipe{animation:wipe .6s cubic-bezier(.2,.8,.2,1) both;transform-origin:0 0}@keyframes wipe{from{transform:scaleX(0)}}"
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


def plate_teststand(t) -> str:
    COLS, CW = 4, (W - 2 * M) / 4
    ROW_H = 372
    TOP = 92
    H = TOP + 2 * ROW_H + 70
    odo = Odo()
    o = sheet_frame(t, H, H - M, cols="ABCDEFGH", grid=True)
    o.append(label(M + 22, 70, "Test stand  ·  eight engagements, one reading each", t, t["accent"], 12.5))
    o.append(text(W - M - 22, 72, "Every needle stops at a number from the record below.", "serif-i", 22, t["ink3"], "end"))
    o.append(rule(M + 22, 88, W - M - 22, 88, t["rule"], 0.8))
    A0, SWEEP = 135, 270
    css = []
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
        # graduations: 50 minor, 10 major
        for k in range(51):
            a = A0 + SWEEP * k / 50
            major = k % 5 == 0
            x1, y1 = P(a, R - (14 if major else 8))
            x2, y2 = P(a, R)
            o.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{t["rule_ink"] if major else t["rule"]}" '
                     f'stroke-width="{1.3 if major else 0.7}" class="fi"{d_(dl+0.2+k*0.012)}/>')
        # the reading band, swept in with the needle
        ar = R - 22
        sx, sy = P(A0, ar)
        ea = A0 + SWEEP * f
        exx, eyy = P(ea, ar)
        large = 1 if SWEEP * f > 180 else 0
        o.append(f'<path d="M{sx:.1f},{sy:.1f} A{ar},{ar} 0 1 1 {P(A0+SWEEP, ar)[0]:.1f},{P(A0+SWEEP, ar)[1]:.1f}" fill="none" '
                 f'stroke="{t["rule_faint"]}" stroke-width="7"/>')
        o.append(f'<path d="M{sx:.1f},{sy:.1f} A{ar},{ar} 0 {large} 1 {exx:.1f},{eyy:.1f}" pathLength="1" fill="none" '
                 f'stroke="{t["accent"]}" stroke-width="7" class="band" style="animation-delay:{dl+0.6:.2f}s"/>')
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
                 f'<g style="animation:{kname} 2.4s cubic-bezier(.3,.1,.3,1) {dl+0.6:.2f}s both">'
                 f'<g class="tremor" style="animation-delay:{-i*0.37:.2f}s">'
                 f'<path d="M-16,-3.2 L{R-10},-0.9 L{R-4},0 L{R-10},0.9 L-16,3.2 Z" fill="{t["accent"]}"/>'
                 f'<path d="M-16,0 H{R-6}" stroke="{t["sheet"]}" stroke-width="0.6" stroke-opacity=".6"/>'
                 '</g></g></g>')
        o.append(f'<circle cx="{gx:.1f}" cy="{gy}" r="9" fill="{t["sheet"]}" stroke="{t["accent"]}" stroke-width="2"/>')
        o.append(f'<circle cx="{gx:.1f}" cy="{gy}" r="2.6" fill="{t["accent"]}"/>')
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
            f'<stop offset="1" stop-color="{t["accent"]}" stop-opacity="0"/></radialGradient></defs>')
    css_all = (odo.css() + "".join(css) +
               ".band{stroke-dasharray:1 1;animation:dr 2.2s cubic-bezier(.3,.1,.3,1) both}"
               ".tremor{animation:tremor 2.9s ease-in-out infinite alternate}"
               "@keyframes tremor{0%{transform:rotate(-.5deg)}40%{transform:rotate(.35deg)}70%{transform:rotate(-.15deg)}100%{transform:rotate(.6deg)}}")
    alt = "Test stand. Eight gauges, one per kind of work: " + "; ".join(
        f"{k}: {v} {r} ({c})" for k, v, _, _, r, c in GAUGES) + "."
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
    H = 780
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
                 f'<ellipse cx="{lx:.1f}" cy="{ly}" rx="{w*0.75:.1f}" ry="{(RY1-RY0)*0.62:.1f}" fill="url(#lamp)"/></g>')

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
    nx, ny = W - M - 19, RY0 + 52
    o.append(f'<circle cx="{nx}" cy="{ny}" r="13" fill="{t["sheet"]}" stroke="{t["rule_strong"]}" stroke-width="0.9"/>')
    o.append(f'<path d="M{nx},{ny-18} V{ny+18}" stroke="{t["rule"]}" stroke-width="0.7"/>')
    o.append(f'<g transform="translate({nx},{ny})"><g class="needleN"><path d="M0,-12 L4.6,6 L0,2.4 L-4.6,6 Z" fill="{t["accent"]}"/></g></g>')
    o.append(text(nx, ny - 22, "N", "mono-m", 11, t["ink2"], "middle"))
    o += title_block(t, TBY, [("drawing", "Key plan", 190), ("sheet", "G-000", 130), ("domains", str(len(zones)), 130),
                              ("sheets", str(total), 120), ("scale", "NTS", 110),
                              ("note", "the corridor is where the ideas walk in", W - 2 * M - 680)])

    css = (".lit{opacity:0;animation:lit 20s ease-in-out infinite both}"
           "@keyframes lit{0%{opacity:0}4.5%{opacity:1}19%{opacity:1}23%{opacity:0}100%{opacity:0}}"
           ".lamp{animation:lamp 20s ease-in-out infinite both}"
           "@keyframes lamp{0%{opacity:.25}4.5%{opacity:1}19%{opacity:1}23%{opacity:.25}100%{opacity:.25}}"
           ".door{animation:door 1.3s cubic-bezier(.3,1.5,.5,1) both}@keyframes door{from{transform:rotate(90deg)}}"
           ".tag{animation:tag .7s cubic-bezier(.3,1.6,.5,1) both}@keyframes tag{from{opacity:0;transform:scale(0)}}"
           ".march{animation:march 1.4s linear infinite}@keyframes march{to{stroke-dashoffset:-18}}"
           ".ping{transform-box:fill-box;transform-origin:50% 50%;animation:ping 2s ease-out infinite}"
           "@keyframes ping{from{transform:scale(.6);opacity:1}to{transform:scale(2.2);opacity:0}}"
           ".needleN{animation:nn 2.6s cubic-bezier(.3,1.6,.4,1) .6s both}@keyframes nn{from{transform:rotate(-200deg)}}")
    alt = (f"Key plan, sheet G-000: a floor plan of the work. {len(zones)} rooms off one corridor, one per domain, "
           + "; ".join(f"{z['title']} ({len(z['projects'])} sheets: " + ", ".join(p["name"] for p in z["projects"]) + ")" for z in zones)
           + ". A camera visits each room in turn and its light comes on, while someone in the corridor walks to its door.")
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
                o.append(f'<g class="hl s{k}"><rect x="{EX0}" y="{y:.1f}" width="{wv:.1f}" height="{th:.1f}" fill="{t["accent"]}" fill-opacity=".42"/>'
                         f'<path d="M{EX0+wv:.1f},{y:.1f} v{th:.1f}" stroke="{t["accent"]}" stroke-width="2"/></g>')
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
        o.append(f'<g class="hl s{k}">'
                 + text(HX, 204, tk["name"], "serif", 54, t["ink"])
                 + text(HX + 2, 232, tk["sub"], "serif-i", 20, t["ink3"])
                 + text(HX, 312, str(tk["n"]), "serif", 72, t["accent"])
                 + text(HX + 2, 338, f"materials across {tk['d']} disciplines", "mono", 12.5, t["ink2"]) + "</g>")
    qy = 382
    o.append(rule(HX, qy - 18, HX + 330, qy - 18, t["rule"], 0.8))
    for k, tk in enumerate(tr):
        yy = qy + k * 24
        o.append(text(HX + 18, yy + 4, tk["code"], "mono", 11.5, t["ink4"]) + text(HX + 72, yy + 4, tk["name"], "mono-m", 13, t["ink3"])
                 + text(HX + 330, yy + 4, f"{tk['n']}", "mono", 12, t["ink4"], "end"))
        o.append(f'<g class="hl s{k}"><rect x="{HX}" y="{yy-11}" width="334" height="22" fill="{t["accent_soft"]}"/>'
                 f'<circle cx="{HX+7}" cy="{yy}" r="3.2" fill="{t["accent"]}"/>'
                 + text(HX + 72, yy + 4, tk["name"], "mono-m", 13, t["accent"]) + "</g>")

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
            o.append(f'<g class="hl s{k}">' + text(X0 + 14, y + sh - 16, msg, "mono-m", 11.5, t["accent"] if u else t["ink4"]) + "</g>")
        for li, line in enumerate(lines):
            cy = y + SP + li * (CH + RG)
            x = CX0
            for j, (it, w) in enumerate(line):
                heavy = it["n"] >= 3
                fill = t["raised"] if heavy else "none"
                stroke = t["rule_strong"] if heavy else t["rule"]
                slots = [k for k, tk in enumerate(tr) if it["name"] in tk["used"][ci]]
                hl = "".join(f'<g class="hl s{k}"><rect x="{x-2.5:.1f}" y="{cy-2.5}" width="{w+5:.1f}" height="{CH+5}" rx="5" fill="none" '
                             f'stroke="{t["accent"]}" stroke-opacity=".3" stroke-width="3"/>'
                             f'<rect x="{x:.1f}" y="{cy}" width="{w:.1f}" height="{CH}" rx="3" fill="{t["accent"]}" '
                             f'fill-opacity="{0.34 if t["glow_op"] > .5 else 0.22}" stroke="{t["accent"]}" stroke-width="1.8"/></g>' for k in slots)
                o.append(f'<g class="chip"{d_(dl + li * 0.04 + j * 0.02)}>'
                         f'<rect x="{x:.1f}" y="{cy}" width="{w:.1f}" height="{CH}" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="0.9"/>{hl}'
                         + text(x + PADX, cy + 17.5, it["name"], "mono-m" if heavy else "mono", FS, t["ink"])
                         + text(x + w - PADX, cy + 17.5, str(it["n"]), "mono", FC, t["ink4"], "end") + "</g>")
                x += w + GAP
        y += sh
    o.append(rule(X0, y, X1, y, t["rule_strong"], 1.2))
    ly = y + 26
    o.append(label(X0 + 14, ly + 12, "legend", t, t["ink4"], 11))
    o.append(f'<rect x="{CX0}" y="{ly}" width="22" height="16" rx="3" fill="{t["raised"]}" stroke="{t["rule_strong"]}" stroke-width="0.9"/>')
    o.append(text(CX0 + 32, ly + 12.5, "in three or more", "mono-m", 12.5, t["ink3"]))
    o.append(f'<rect x="{CX0+196}" y="{ly}" width="22" height="16" rx="3" fill="none" stroke="{t["rule"]}" stroke-width="0.9"/>')
    o.append(text(CX0 + 228, ly + 12.5, "in one or two", "mono", 12.5, t["ink3"]))
    o.append(f'<rect x="{CX0+380}" y="{ly}" width="22" height="16" rx="3" fill="{t["accent"]}" fill-opacity=".34" stroke="{t["accent"]}" stroke-width="1.8"/>')
    o.append(text(CX0 + 412, ly + 12.5, "used by the project being traced", "mono", 12.5, t["ink3"]))

    css = (".lay{animation:lay .8s cubic-bezier(.3,1.4,.5,1) both}@keyframes lay{from{opacity:0;transform:translateY(-26px)}}"
           ".chip{animation:chip .6s cubic-bezier(.2,.8,.2,1) both}@keyframes chip{from{opacity:0;transform:translateY(8px)}}"
           f".hl{{opacity:0;animation:hl {CYCLE:.0f}s ease-in-out infinite both}}"
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


def plate_telemetry(t, s, updated) -> str:
    H = 860
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

    # ---- propellant: languages, by repositories that use them
    langs = [l for l in s["languages_by_repos"] if l["name"] != "Jupyter Notebook"][:8]
    mxr = max(l["repos"] for l in langs) if langs else 1
    ty0 = 600
    o.append(label(M + 22, ty0, "propellant  ·  languages, by repositories that use them", t, t["ink3"], 11))
    TW, TH = 54, 128
    gap = (W - 2 * M - 44) / len(langs)
    tanks_css = []
    for i, l in enumerate(langs):
        x = M + 22 + i * gap + (gap - TW) / 2
        y = ty0 + 28
        lvl = TH * l["repos"] / mxr
        cid = f"tk{i}"
        o.append(f'<defs><clipPath id="{cid}"><rect x="{x}" y="{y}" width="{TW}" height="{TH}" rx="{TW/2}"/></clipPath></defs>')
        o.append(f'<rect x="{x}" y="{y}" width="{TW}" height="{TH}" rx="{TW/2}" fill="{t["deep"]}" stroke="{t["rule_strong"]}" stroke-width="1.1"/>')
        wave = (f"M{x-TW},{0} " + " ".join(f"q{TW/4:.1f},-5 {TW/2:.1f},0 t{TW/2:.1f},0" for _ in range(3)) +
                f" V{TH+20} H{x-TW} Z")
        fill = t["accent"] if i == 0 else t["ink3"]
        k = f"fill{i}"
        tanks_css.append(f"@keyframes {k}{{from{{transform:translateY({lvl:.1f}px)}}}}")
        o.append(f'<g clip-path="url(#{cid})"><g transform="translate(0,{y+TH-lvl:.1f})">'
                 f'<g style="animation:{k} 2.2s cubic-bezier(.2,.8,.2,1) {0.6+i*0.12:.2f}s both">'
                 f'<g class="wave" style="animation-delay:{-i*0.4:.2f}s"><path d="{wave}" fill="{fill}" fill-opacity="{0.9 if i == 0 else 0.45}"/></g>'
                 f'</g></g></g>')
        for k2 in range(1, 4):
            yy = y + TH * k2 / 4
            o.append(rule(x + TW - 10, yy, x + TW - 2, yy, t["rule"], 0.8))
        o.append(f'<path d="M{x+10},{y+16} V{y+TH-16}" stroke="#fff" stroke-opacity=".12" stroke-width="5" stroke-linecap="round"/>')
        o.append(text(x + TW / 2, y + TH + 26, l["name"], "mono-m", 13, t["ink2"], "middle"))
        o.append(text(x + TW / 2, y + TH + 46, f'{l["repos"]} repo{"s" if l["repos"] != 1 else ""}', "mono", 12, t["ink4"], "middle"))

    defs = ('<defs>'
            f'<linearGradient id="burnA" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t["phosphor"]}" stop-opacity="{0.32 if t["glow_op"]>.5 else 0.18}"/>'
            f'<stop offset="1" stop-color="{t["phosphor"]}" stop-opacity="0"/></linearGradient>'
            f'<radialGradient id="beamG"><stop offset="0" stop-color="{t["phosphor"]}" stop-opacity=".9"/><stop offset="1" stop-color="{t["phosphor"]}" stop-opacity="0"/></radialGradient>'
            '<filter id="blur3" x="-5%" y="-20%" width="110%" height="140%"><feGaussianBlur stdDeviation="3"/></filter>'
            '</defs>')
    css = (odo.css() + "".join(tanks_css) +
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
# Plate 6: the closing sheet. The same engine, on a vehicle, leaving.
# --------------------------------------------------------------------------
def rocket(t):
    """A launch vehicle in elevation, local units, engine bell at y=0."""
    ink, strong, faint = t["rule_ink"], t["rule_strong"], t["rule"]
    o = [
        # body
        f'<path d="M-17,-18 V-196 C-17,-232 -8,-258 0,-272 C8,-258 17,-232 17,-196 V-18 Z" fill="{t["sheet"]}" stroke="{ink}" stroke-width="1.4"/>',
        f'<path d="M-17,-120 H17 M-17,-196 H17 M-17,-60 H17" stroke="{strong}" stroke-width="0.8"/>',
        f'<path d="M-6,-196 V-120" stroke="{faint}" stroke-width="0.6"/>',
        f'<circle cx="0" cy="-214" r="5" fill="none" stroke="{strong}" stroke-width="0.9"/>',
        # fins
        f'<path d="M-17,-56 L-34,-14 V-4 L-17,-18 Z M17,-56 L34,-14 V-4 L17,-18 Z" fill="{t["raised"]}" stroke="{ink}" stroke-width="1.2"/>',
        # bell
        f'<path d="M-9,-18 L-14,0 H14 L9,-18 Z" fill="{t["sunk"]}" stroke="{ink}" stroke-width="1.2"/>',
        text(0, -150, "GH-01", "mono-m", 8, t["accent"], "middle", extra=' transform="rotate(-90 0 -150)"'),
    ]
    return "".join(o)


def plate_closing(t, updated, rev) -> str:
    H = 470
    TBY = H - M - 50
    o = sheet_frame(t, H, TBY, cols="ABCDEFGHJK")
    o.append(f'<g class="up"{d_(0.2)}>' + text(70, 172, "In thrust we trust.", "serif-i", 84, t["accent"]) + "</g>")
    o.append(f'<g class="up"{d_(0.45)}>' + text(72, 222, "Reliability is a feature. So is honesty about", "sans", 22, t["ink2"]) +
             text(72, 252, "what isn't done yet.", "sans", 22, t["ink2"]) + "</g>")
    o.append(line_pen(72, 290, 252, 290, t["rule_strong"], 1, 0.7, 0.8))
    o.append(label(72, 322, "akshaybajpai.com  ·  contact@akshaybajpai.com", t, t["ink3"], 12.5, extra=f' class="mono-m fi"{d_(0.9)}'))

    # ---- the pad, the tower, the vehicle
    px, py = 930, TBY - 34
    o.append(f'<defs><clipPath id="sky"><rect x="{M}" y="{M}" width="{W-2*M}" height="{TBY-M}"/></clipPath>'
             f'<radialGradient id="smk"><stop offset="0" stop-color="{t["smoke"]}" stop-opacity=".55"/>'
             f'<stop offset=".7" stop-color="{t["smoke"]}" stop-opacity=".22"/><stop offset="1" stop-color="{t["smoke"]}" stop-opacity="0"/></radialGradient>'
             f'<linearGradient id="pl" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t["fire_core"]}"/>'
             f'<stop offset=".35" stop-color="{t["fire_mid"]}" stop-opacity=".9"/><stop offset="1" stop-color="{t["fire_outer"]}" stop-opacity="0"/></linearGradient>'
             f'<radialGradient id="padG"><stop offset="0" stop-color="{t["fire_mid"]}" stop-opacity="{0.6*t["glow_op"]+0.1:.2f}"/>'
             f'<stop offset="1" stop-color="{t["fire_mid"]}" stop-opacity="0"/></radialGradient></defs>')
    o.append(f'<g clip-path="url(#sky)">')
    # ground and pad
    o.append(rule(560, py + 26, W - M, py + 26, t["rule_strong"], 1))
    for k in range(30):
        xx = 566 + k * 20
        o.append(rule(xx, py + 26, xx - 8, py + 34, t["rule"], 0.7))
    o.append(f'<path d="M{px-70},{py+26} V{py+4} H{px-24} L{px-14},{py+18} H{px+14} L{px+24},{py+4} H{px+70} V{py+26}" fill="{t["sunk"]}" stroke="{t["rule_ink"]}" stroke-width="1.2"/>')
    o.append(f'<ellipse cx="{px}" cy="{py+16}" rx="160" ry="40" fill="url(#padG)" class="padglow"/>')
    # tower: a lattice, with an arm that swings clear at ignition
    tx = px - 96
    o.append(f'<path d="M{tx-14},{py+4} V{py-300} M{tx+14},{py+4} V{py-300}" stroke="{t["rule_ink"]}" stroke-width="1.2"/>')
    for k in range(15):
        y1 = py + 4 - k * 20
        o.append(f'<path d="M{tx-14},{y1} L{tx+14},{y1-20} M{tx+14},{y1} L{tx-14},{y1-20} M{tx-14},{y1-20} H{tx+14}" stroke="{t["rule"]}" stroke-width="0.7"/>')
    o.append(f'<g transform="translate({tx+14},{py-210})"><g class="arm">'
             f'<path d="M0,0 H58 V8 H0 Z" fill="{t["raised"]}" stroke="{t["rule_ink"]}" stroke-width="1"/></g></g>')
    # smoke that billows out along the ground
    rnd = random.Random(11)
    for k in range(16):
        side = -1 if k % 2 else 1
        dx = side * rnd.uniform(60, 260)
        dy = -rnd.uniform(4, 70)
        r = rnd.uniform(22, 44)
        o.append(f'<circle cx="{px + side*rnd.uniform(0, 30):.1f}" cy="{py+10:.1f}" r="{r:.1f}" fill="url(#smk)" class="smoke fb" '
                 f'style="--dx:{dx:.1f}px;--dy:{dy:.1f}px;animation-delay:{rnd.uniform(0, 0.8):.2f}s"/>')
    # the vehicle and its plume, which leave together
    o.append(f'<g transform="translate({px},{py})"><g class="vehicle">'
             f'<g class="plume"><path d="M-14,0 C-22,60 -12,150 0,230 C12,150 22,60 14,0 Z" fill="url(#pl)" class="fb fl2"/>'
             f'<path d="M-8,0 C-10,30 -4,70 0,110 C4,70 10,30 8,0 Z" fill="{t["fire_core"]}" fill-opacity=".9" class="fb fl3"/></g>'
             f'{rocket(t)}</g></g>')
    # vapour venting from the tank while it waits
    for k in range(4):
        o.append(f'<circle cx="{px+18}" cy="{py-150}" r="7" fill="url(#smk)" class="vent fb" style="animation-delay:{k*0.8:.2f}s"/>')
    o.append("</g>")
    # countdown readout
    o.append(label(px + 110, py - 200, "launch window", t, t["accent"], 11))
    o.append(text(px + 110, py - 172, "every 14 s", "mono-m", 17, t["ink"]))
    o.append(label(px + 110, py - 132, "status", t, t["ink4"], 11))
    o.append(f'<g class="status">' + text(px + 110, py - 106, "HOLD", "mono-m", 17, t["ink2"]) + "</g>")
    o.append(f'<g class="status2">' + text(px + 110, py - 106, "LIFTOFF", "mono-m", 17, t["accent"]) + "</g>")

    o.append(rule(M, TBY, W - M, TBY, t["rule_strong"], 1.2))
    o.append(rule(M, TBY + 3, W - M, TBY + 3, t["rule_faint"], 0.8))
    o.append(label(M + 16, TBY + 32, f"end of set  ·  sheet GH-01 of 01  ·  rev {rev}", t, t["ink3"], 12))
    o.append(label(W - M - 16, TBY + 32, f"last updated {updated}", t, t["accent"], 12, "end"))
    cycle = 14
    css = (FIRE_CSS +
           f".vehicle{{animation:lift {cycle}s cubic-bezier(.55,0,.9,.5) infinite}}"
           "@keyframes lift{0%,34%{transform:translateY(0);opacity:1}70%{transform:translateY(-560px);opacity:1}"
           "70.5%{transform:translateY(-560px);opacity:0}71%{transform:translateY(0);opacity:0}86%{opacity:0}100%{opacity:1}}"
           f".plume{{transform-box:fill-box;transform-origin:50% 0;animation:plume {cycle}s ease-out infinite}}"
           "@keyframes plume{0%,25%{opacity:0;transform:scaleY(.1)}29%{opacity:1;transform:scaleY(.6)}36%{transform:scaleY(1)}60%{transform:scaleY(1.6)}70%{opacity:1}71%,100%{opacity:0}}"
           ".plume{opacity:0}"
           f".smoke{{opacity:0;transform-origin:50% 50%;animation:smoke {cycle}s ease-out infinite}}"
           "@keyframes smoke{0%,26%{opacity:0;transform:translate(0,0) scale(.3)}32%{opacity:1}"
           "62%{opacity:.85;transform:translate(var(--dx),var(--dy)) scale(1.9)}88%,100%{opacity:0;transform:translate(calc(var(--dx)*1.3),calc(var(--dy) - 30px)) scale(2.4)}}"
           f".padglow{{opacity:0;animation:padg {cycle}s ease-out infinite}}"
           "@keyframes padg{0%,26%{opacity:0}31%{opacity:1}44%{opacity:.8}60%,100%{opacity:0}}"
           f".arm{{animation:arm {cycle}s ease-in-out infinite}}"
           "@keyframes arm{0%,18%{transform:rotate(0)}26%,86%{transform:rotate(-72deg)}96%,100%{transform:rotate(0)}}"
           f".vent{{opacity:0;animation:vent {cycle}s ease-out infinite}}"
           "@keyframes vent{0%{opacity:0;transform:translate(0,0) scale(.5)}2%{opacity:.8}16%{opacity:0;transform:translate(46px,-26px) scale(2.6)}100%{opacity:0}}"
           f".status{{animation:st1 {cycle}s steps(1) infinite}}@keyframes st1{{0%{{opacity:1}}30%{{opacity:0}}88%{{opacity:1}}}}"
           f".status2{{opacity:0;animation:st2 {cycle}s steps(1) infinite}}@keyframes st2{{0%{{opacity:0}}30%{{opacity:1}}88%{{opacity:0}}}}")
    css += "@media (prefers-reduced-motion:reduce){.status2,.plume,.smoke,.padglow{display:none}}"
    return svg(W, H, "\n".join(o), ("serif-i", "mono", "mono-m", "sans"),
               f"End of set. In thrust we trust. Reliability is a feature. So is honesty about what isn't done yet. "
               f"A launch vehicle lifts off the pad. Last updated {updated}.", css)


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


def sync_readme(stack, updated) -> None:
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
        (out / "keyplan.svg").write_text(plate_keyplan(t, zones))
        (out / "schedule.svg").write_text(plate_schedule(t, stack, zones))
        (out / "numbers.svg").write_text(plate_telemetry(t, stats, updated))
        (out / "closing.svg").write_text(plate_closing(t, updated, rev))
        for key, code, title, note, seq in headers:
            (out / f"h-{key}.svg").write_text(plate_header(t, code, title, note, seq))
    sync_readme(stack, updated)
    print(f"updated {updated} rev {rev}: {len(list(ASSETS.glob('*/*.svg')))} plates")


if __name__ == "__main__":
    main()
