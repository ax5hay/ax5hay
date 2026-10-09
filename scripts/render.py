#!/usr/bin/env python3
"""Render the profile README's plates as SVG, in a light and a dark issue.

Everything the README shows as an image is drawn here from data/*.json, with
the site's own type (Instrument Serif, IBM Plex Mono) embedded so GitHub's
image proxy renders it the same everywhere. Standard library only.

    python scripts/render.py                    # re-issue every plate
    GITHUB_TOKEN=... python scripts/render.py   # also refresh data/stats.json
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import subprocess
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
DATA = ROOT / "data"
W = 920            # every plate shares the README column width
FIRST_ISSUE = "2026-10-10"

# --------------------------------------------------------------------------
# Issue states. These are the site's "artifact" (paper) and "annotated"
# (night blueprint) modes, token for token, so the profile reads as one more
# sheet in the same set.
# --------------------------------------------------------------------------
THEMES = {
    "light": dict(
        board="#ded2b8", sheet="#fcfaf4", raised="#ffffff", sunk="#f1ece0",
        ink="#141417", ink2="#413c34", ink3="#5c5548", ink4="#6f6655",
        rule_faint="rgba(20,20,23,0.12)", rule="rgba(20,20,23,0.28)",
        rule_strong="rgba(20,20,23,0.62)", rule_ink="rgba(20,20,23,0.9)",
        grid_minor="rgba(20,20,23,0.06)", grid_major="rgba(20,20,23,0.115)",
        accent="#983729", accent_soft="rgba(152,55,41,0.14)",
        accent_line="rgba(152,55,41,0.55)", accent2="#2f5d8c",
        grain=0.055,
    ),
    "dark": dict(
        board="#05182a", sheet="#082139", raised="#0c2b49", sunk="#041322",
        ink="#e6f1fc", ink2="#9dbdd9", ink3="#7b9ebf", ink4="#6a8dab",
        rule_faint="rgba(157,207,255,0.12)", rule="rgba(157,207,255,0.28)",
        rule_strong="rgba(198,227,255,0.62)", rule_ink="rgba(230,241,252,0.92)",
        grid_minor="rgba(140,195,255,0.09)", grid_major="rgba(140,195,255,0.16)",
        accent="#ffc75a", accent_soft="rgba(255,199,90,0.16)",
        accent_line="rgba(255,199,90,0.7)", accent2="#6fe3a0",
        grain=0.045,
    ),
}

FONT_FILES = {
    "serif": ("InstrumentSerif-Regular.woff2", "normal"),
    "serif-i": ("InstrumentSerif-Italic.woff2", "italic"),
    "mono": ("IBMPlexMono-Regular.woff2", "normal"),
    "mono-m": ("IBMPlexMono-Medium.woff2", "normal"),
}
MONO_ADVANCE = 0.6  # IBM Plex Mono: 600/1000 em per glyph


def font_faces(*keys: str) -> str:
    out = []
    for k in keys:
        name, style = FONT_FILES[k]
        b64 = base64.b64encode((ASSETS / "fonts" / name).read_bytes()).decode()
        out.append(
            f'@font-face{{font-family:"{k}";font-style:{style};font-weight:400;'
            f'src:url(data:font/woff2;base64,{b64}) format("woff2");}}'
        )
    return "".join(out)


def mono_w(text: str, size: float, tracking: float = 0.0) -> float:
    return len(text) * size * (MONO_ADVANCE + tracking)


def svg(width: int, height: int, body: str, fonts: tuple[str, ...], title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="t">\n'
        f"<title id=\"t\">{escape(title)}</title>\n"
        f"<style>{font_faces(*fonts)}"
        ".serif{font-family:serif,Georgia,'Times New Roman',serif}"
        ".serif-i{font-family:serif-i,Georgia,serif;font-style:italic}"
        ".mono{font-family:mono,'IBM Plex Mono',ui-monospace,Menlo,monospace}"
        ".mono-m{font-family:mono-m,'IBM Plex Mono',ui-monospace,Menlo,monospace}"
        "text{white-space:pre}"
        "</style>\n"
        f"{body}\n</svg>\n"
    )


def text(x, y, s, cls, size, fill, anchor="start", tracking=None, extra=""):
    ls = f' letter-spacing="{tracking}em"' if tracking else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" font-size="{size}" fill="{fill}" '
        f'text-anchor="{anchor}"{ls}{extra}>{escape(s)}</text>'
    )


def label(x, y, s, t, fill=None, size=9.5, anchor="start"):
    """A drafting label: small uppercase mono, tracked wide."""
    return text(x, y, s.upper(), "mono-m", size, fill or t["ink4"], anchor, tracking=0.16)


def rule(x1, y1, x2, y2, stroke, w=1.0, dash=""):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{stroke}" stroke-width="{w}"{d} stroke-linecap="square"/>'
    )


def grid_defs(t, idp="g"):
    return (
        f'<pattern id="{idp}" width="24" height="24" patternUnits="userSpaceOnUse">'
        f'<path d="M24 0H0V24" fill="none" stroke="{t["grid_minor"]}" stroke-width="0.5"/></pattern>'
        f'<pattern id="{idp}M" width="120" height="120" patternUnits="userSpaceOnUse">'
        f'<rect width="120" height="120" fill="url(#{idp})"/>'
        f'<path d="M120 0H0V120" fill="none" stroke="{t["grid_major"]}" stroke-width="0.6"/></pattern>'
    )


def grain_defs(t, idp="grain"):
    """Paper tooth: a touch of turbulence laid over the sheet."""
    return (
        f'<filter id="{idp}" x="0" y="0" width="100%" height="100%">'
        '<feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch" result="n"/>'
        f'<feColorMatrix type="matrix" values="0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 {t["grain"]} 0"/>'
        "</filter>"
    )


def grain(x, y, w, h, idp="grain"):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" filter="url(#{idp})" pointer-events="none"/>'


def sheet_frame(t, H, field_bottom):
    """The board, the sheet, its margin, and the grid references on the edge."""
    o = [f'<rect width="{W}" height="{H}" fill="{t["board"]}"/>',
         f'<defs>{grid_defs(t)}{grain_defs(t)}</defs>',
         f'<rect x="12" y="12" width="{W-24}" height="{H-24}" fill="{t["sheet"]}" stroke="{t["rule_strong"]}" stroke-width="1"/>',
         f'<rect x="30" y="30" width="{W-60}" height="{field_bottom-30}" fill="url(#gM)"/>',
         f'<rect x="30" y="30" width="{W-60}" height="{H-60}" fill="none" stroke="{t["rule"]}" stroke-width="0.6"/>']
    cols = "ABCDEFGH"
    for i, c in enumerate(cols):
        x = 30 + (W - 60) * (i + 0.5) / len(cols)
        o.append(text(x, 24, c, "mono", 8.5, t["ink4"], "middle"))
        o.append(text(x, H - 15, c, "mono", 8.5, t["ink4"], "middle"))
        if i:
            xx = 30 + (W - 60) * i / len(cols)
            o.append(rule(xx, 12, xx, 18, t["rule"], 0.6))
            o.append(rule(xx, H - 18, xx, H - 12, t["rule"], 0.6))
    rows = max(2, round((H - 60) / 110))
    for i in range(rows):
        y = 30 + (H - 60) * (i + 0.5) / rows
        o.append(text(21, y + 3, str(i + 1), "mono", 8.5, t["ink4"], "middle"))
        o.append(text(W - 21, y + 3, str(i + 1), "mono", 8.5, t["ink4"], "middle"))
        if i:
            yy = 30 + (H - 60) * i / rows
            o.append(rule(12, yy, 18, yy, t["rule"], 0.6))
            o.append(rule(W - 18, yy, W - 12, yy, t["rule"], 0.6))
    return o


def stamp(x, y, head, body, t, angle=-7):
    """The inspector's stamp: last updated, in the sheet's one hot colour."""
    w, h = 168, 58
    return (
        f'<g transform="translate({x},{y}) rotate({angle})" opacity="0.92">'
        f'<rect x="{-w/2}" y="{-h/2}" width="{w}" height="{h}" rx="3" fill="{t["sheet"]}" fill-opacity="0.65" stroke="{t["accent"]}" stroke-width="1.6"/>'
        f'<rect x="{-w/2+4}" y="{-h/2+4}" width="{w-8}" height="{h-8}" rx="2" fill="none" stroke="{t["accent"]}" stroke-width="0.6"/>'
        + text(0, -h / 2 + 20, head.upper(), "mono-m", 9.5, t["accent"], "middle", tracking=0.22)
        + text(0, h / 2 - 11, body, "mono-m", 17, t["accent"], "middle", tracking=0.06)
        + "</g>"
    )


# --------------------------------------------------------------------------
# Plate 1: the title sheet
# --------------------------------------------------------------------------
def plate_hero(t, stats, updated, rev) -> str:
    H = 540
    TB = H - 30 - 52  # title block top
    o = sheet_frame(t, H, TB)

    # ---- left field: the name and the thesis
    o.append(label(58, 84, "Sheet GH-01 · GitHub profile", t, t["accent"]))
    o.append(text(56, 170, "Akshay Bajpai", "serif", 78, t["ink"]))
    o.append(text(58, 222, "In thrust we trust.", "serif-i", 36, t["accent"]))
    o.append(rule(58, 250, 178, 250, t["rule_strong"], 0.8))
    o.append(text(58, 284, "I build reliable, robust software systems,", "mono", 13, t["ink2"]))
    o.append(text(58, 304, "AI or otherwise. The kind that holds under", "mono", 13, t["ink2"]))
    o.append(text(58, 324, "load, states its own assumptions, and fails", "mono", 13, t["ink2"]))
    o.append(text(58, 344, "loud instead of silent.", "mono", 13, t["ink2"]))
    o.append(label(58, 386, "AI architect  ·  forward-deployed AI engineer", t, t["ink3"]))
    o.append(label(58, 406, "Systems that behave: LLM, vision, edge, data", t, t["ink4"]))

    # ---- right field: the engine, in section
    o.append(engine_section(t, cx=586, top=50))

    # ---- title block
    o.append(rule(30, TB, W - 30, TB, t["rule_strong"], 1))
    o.append(rule(30, TB + 3, W - 30, TB + 3, t["rule_faint"], 0.6))
    cells = [
        ("drawn by", "ax5hay", 150),
        ("title", "GitHub profile", 190),
        ("sheet", "GH-01 of 01", 150),
        ("scale", "NTS", 90),
        ("first issued", FIRST_ISSUE, 150),
        ("rev", str(rev), 0),
    ]
    x = 30
    for i, (lab, val, w) in enumerate(cells):
        if i:
            o.append(rule(x, TB, x, H - 30, t["rule"], 0.6))
        o.append(label(x + 12, TB + 20, lab, t))
        o.append(text(x + 12, TB + 42, val, "mono-m", 13, t["ink"]))
        x += w
    o.append(grain(12, 12, W - 24, H - 24))
    o.append(stamp(W - 150, TB - 36, "last updated", updated, t))
    return svg(W, H, "\n".join(o), ("serif", "serif-i", "mono", "mono-m"),
               f"Akshay Bajpai. In thrust we trust. Sheet GH-01, the GitHub profile title sheet, last updated {updated}.")


def engine_section(t, cx: float, top: float) -> str:
    """A thrust chamber and bell nozzle, drawn as a drafting detail.

    Thrust is the easy part; the callouts are the control surfaces that turn
    it into trust. The leaders are the sheet's one hot colour.
    """
    ink, acc = t["rule_ink"], t["accent"]
    o = []
    y0 = top
    dome_y, cham_top, cham_bot, throat_y, exit_y = y0 + 40, y0 + 62, y0 + 142, y0 + 184, y0 + 300
    rc, rt, re_ = 40, 15, 84   # chamber, throat and exit radii

    def wall(sign, off=0.0):
        s = sign
        return (f"M{cx+s*(rc-off)},{cham_top} V{cham_bot} "
                f"Q{cx+s*(rc-off)},{throat_y-10} {cx+s*(rt+off*0.4)},{throat_y} "
                f"Q{cx+s*(rc-4-off)},{throat_y+70} {cx+s*(re_-off*1.2)},{exit_y}")

    # centreline, dash-dot: the mark of a section drawing
    o.append(rule(cx, y0 + 6, cx, exit_y + 30, t["rule"], 0.6, dash="14 4 2 4"))
    # gimbal mount: the control surface itself
    o.append(f'<path d="M{cx-26},{dome_y-2} L{cx-34},{y0+16} H{cx+34} L{cx+26},{dome_y-2}" fill="none" stroke="{ink}" stroke-width="1.2"/>')
    o.append(f'<circle cx="{cx}" cy="{y0+16}" r="5" fill="{t["sheet"]}" stroke="{ink}" stroke-width="1.2"/>')
    o.append(f'<circle cx="{cx}" cy="{y0+16}" r="1.4" fill="{ink}"/>')
    for s in (-1, 1):
        o.append(f'<path d="M{cx+s*48},{y0+10} L{cx+s*34},{y0+16} L{cx+s*48},{y0+22}" fill="none" stroke="{t["rule_strong"]}" stroke-width="0.8"/>')
        o.append(f'<path d="M{cx+s*48},{y0+10} V{y0+22}" stroke="{t["rule_strong"]}" stroke-width="0.8"/>')
    # injector dome
    o.append(f'<path d="M{cx-rc},{cham_top} Q{cx},{dome_y-30} {cx+rc},{cham_top}" fill="none" stroke="{ink}" stroke-width="1.6"/>')
    o.append(f'<path d="M{cx-rc+6},{cham_top} Q{cx},{dome_y-16} {cx+rc-6},{cham_top}" fill="none" stroke="{t["rule"]}" stroke-width="0.6"/>')
    # injector plate with its ports
    o.append(rule(cx - rc, cham_top, cx + rc, cham_top, ink, 1.6))
    for i in range(-3, 4):
        o.append(f'<circle cx="{cx+i*10.5}" cy="{cham_top+6}" r="1.6" fill="none" stroke="{t["rule_strong"]}" stroke-width="0.7"/>')
    # outer and inner walls: the regenerative cooling jacket between them
    o.append(f'<path d="{wall(-1)}" fill="none" stroke="{ink}" stroke-width="1.7"/>')
    o.append(f'<path d="{wall(1)}" fill="none" stroke="{ink}" stroke-width="1.7"/>')
    o.append(f'<path d="{wall(-1, 7)}" fill="none" stroke="{t["rule_strong"]}" stroke-width="0.7"/>')
    o.append(f'<path d="{wall(1, 7)}" fill="none" stroke="{t["rule_strong"]}" stroke-width="0.7"/>')
    # section hatch in the jacket, along the chamber
    for i in range(7):
        y = cham_top + 10 + i * 10
        o.append(rule(cx - rc, y + 4, cx - rc + 7, y - 2, t["rule_strong"], 0.6))
        o.append(rule(cx + rc - 7, y + 4, cx + rc, y - 2, t["rule_strong"], 0.6))
    # cooling channel ribs down the bell
    for i in range(1, 7):
        f = i / 7
        y = throat_y + (exit_y - throat_y) * f
        r = rt + (re_ - rt) * (f ** 0.72)
        o.append(rule(cx - r + 1, y, cx - r + 7, y - 3, t["rule"], 0.6))
        o.append(rule(cx + r - 7, y - 3, cx + r - 1, y, t["rule"], 0.6))
    # expansion isobars inside the bell
    for i in range(1, 4):
        f = i / 4
        y = throat_y + (exit_y - throat_y) * f
        r = (rt + (re_ - rt) * (f ** 0.72)) - 9
        o.append(f'<path d="M{cx-r},{y} Q{cx},{y+14} {cx+r},{y}" fill="none" stroke="{t["rule_faint"]}" stroke-width="0.8"/>')
    # exit plane
    o.append(rule(cx - re_ - 10, exit_y, cx + re_ + 10, exit_y, t["rule"], 0.6, dash="3 3"))
    # the plume, with its Mach diamonds
    pl = exit_y + 4
    for i in range(3):
        y1, y2 = pl + i * 20, pl + (i + 1) * 20
        w = 26 - i * 6
        o.append(f'<path d="M{cx-w},{y1} L{cx},{y1+10} L{cx+w},{y1} M{cx-w},{y2} L{cx},{y1+10} L{cx+w},{y2}" '
                 f'fill="none" stroke="{t["accent_line"]}" stroke-width="0.8"/>')
    for s in (-1, 1):
        o.append(f'<path d="M{cx+s*40},{pl} Q{cx+s*36},{pl+32} {cx+s*26},{pl+64}" fill="none" stroke="{t["rule_faint"]}" stroke-width="0.8"/>')
    # thrust as a vector, and what it becomes
    o.append(rule(cx, pl + 8, cx, pl + 74, acc, 1.5))
    o.append(f'<path d="M{cx-6},{pl+66} L{cx},{pl+78} L{cx+6},{pl+66}" fill="none" stroke="{acc}" stroke-width="1.5" stroke-linejoin="miter"/>')
    o.append(label(cx - 46, pl + 30, "thrust", t, t["ink3"], 9.5, "end"))
    o.append(text(cx - 46, pl + 50, "Controlled, it is trust.", "serif-i", 19, acc, "end"))

    # callouts: leader, dot at the part, label at the right margin
    lx = cx + 132
    callouts = [
        (cx + 30, y0 + 14, "orchestration", y0 + 12),
        (cx + 28, cham_top + 6, "schema that refuses bad data", cham_top + 2),
        (cx + rt, throat_y, "safety and guardrails", throat_y - 2),
        (cx + 68, exit_y - 52, "observability", exit_y - 54),
    ]
    o.append(f'<circle cx="{cx+68}" cy="{exit_y-52}" r="3.2" fill="none" stroke="{ink}" stroke-width="1"/>')
    for px, py, s, ly in callouts:
        o.append(f'<circle cx="{px}" cy="{py}" r="1.9" fill="{acc}"/>')
        o.append(f'<path d="M{px},{py} L{lx-10},{ly} H{lx-4}" fill="none" stroke="{t["accent_line"]}" stroke-width="0.8"/>')
        o.append(text(lx, ly + 3.5, s, "mono", 10.5, t["ink2"]))
    # the throat: the one dimension that decides everything
    o.append(rule(cx - rt - 46, throat_y, cx - rt - 2, throat_y, t["rule"], 0.6))
    o.append(text(cx - rt - 50, throat_y + 3, "throat", "mono", 8.5, t["ink4"], "end"))
    return "\n".join(o)


# --------------------------------------------------------------------------
# Section headers: a discipline code, the title, a double rule, a note
# --------------------------------------------------------------------------
def plate_header(t, code: str, title: str, note: str = "", seq: str = "") -> str:
    H = 62
    o = [
        f'<rect x="0" y="22" width="30" height="22" fill="{t["accent"]}"/>',
        text(15, 37.5, code, "mono-m", 11, t["sheet"], "middle", tracking=0.08),
        text(46, 41, title, "serif", 34, t["ink"]),
        rule(0, 54, W, 54, t["rule_strong"], 1.2),
        rule(0, 58, W, 58, t["rule"], 0.5),
    ]
    if note:
        o.append(text(W, 40, note, "mono", 10.5, t["ink4"], "end"))
    if seq:
        o.append(label(W, 24, seq, t, t["ink4"], 8.5, "end"))
    return svg(W, H, "\n".join(o), ("serif", "mono", "mono-m"), title)


# --------------------------------------------------------------------------
# Plate 2: the key plan. Rooms are the domains; the names on the walls are
# the sheets filed under them. Walls are poché, doors swing inward.
# --------------------------------------------------------------------------
def plate_keyplan(t, zones) -> str:
    ROW_H, PAD, TOP, WALL = 34, 16, 50, 5
    maxn = max(len(z["projects"]) for z in zones)
    H = TOP + PAD + maxn * ROW_H + 74
    widths = []
    for z in zones:
        longest = max(max(mono_w(p["name"], 13), mono_w(p["sub"], 10)) for p in z["projects"])
        widths.append(max(longest + 2 * PAD + 10, mono_w(z["title"], 9.5, 0.16) + 2 * PAD + 40))
    scale = (W - WALL) / sum(widths)
    widths = [w * scale for w in widths]
    o = [f'<defs>{grid_defs(t, "k")}{grain_defs(t, "kg")}</defs>',
         f'<rect width="{W}" height="{H}" fill="{t["sheet"]}"/>',
         f'<rect x="0" y="0" width="{W}" height="{H}" fill="url(#kM)"/>']
    x = 0.0
    for zi, (z, w) in enumerate(zip(zones, widths)):
        o.append(f'<rect x="{x+WALL}" y="{WALL}" width="{w-WALL}" height="{H-2*WALL-26}" fill="{t["raised"]}" fill-opacity="0.35"/>')
        o.append(f'<circle cx="{x+WALL+PAD+9}" cy="{WALL+PAD+4}" r="10" fill="none" stroke="{t["accent"]}" stroke-width="1"/>')
        o.append(text(x + WALL + PAD + 9, WALL + PAD + 8, z["code"], "mono-m", 11, t["accent"], "middle"))
        o.append(label(x + WALL + PAD + 28, WALL + PAD + 8, z["title"], t, t["ink3"]))
        o.append(rule(x + WALL + PAD, TOP, x + w - PAD, TOP, t["rule"], 0.6))
        for i, p in enumerate(z["projects"]):
            y = TOP + PAD + i * ROW_H
            o.append(text(x + WALL + PAD, y + 12, p["name"], "mono-m", 13, t["ink"]))
            o.append(text(x + WALL + PAD, y + 26, p["sub"], "mono", 10, t["ink4"]))
        n = len(z["projects"])
        o.append(text(x + w - PAD, H - 26 - WALL - 12, f"{n} sheet{'s' if n != 1 else ''}", "mono", 9.5, t["ink4"], "end"))
        x += w
    # walls: poché, the way plans draw what is solid
    o.append(f'<rect x="0" y="0" width="{W}" height="{H-26}" fill="none" stroke="{t["rule_ink"]}" stroke-width="{WALL*2}"/>')
    x = 0.0
    for w in widths[:-1]:
        x += w
        o.append(rule(x + WALL / 2, 0, x + WALL / 2, H - 26, t["rule_ink"], WALL))
    # the doors are cut after the walls so they read as openings
    x = 0.0
    for w in widths:
        dx = x + WALL + 26
        dy = H - 26
        o.append(f'<rect x="{dx}" y="{dy-WALL-1}" width="26" height="{WALL+2}" fill="{t["sheet"]}"/>')
        o.append(f'<path d="M{dx},{dy-WALL} V{dy-WALL-26} A26,26 0 0 1 {dx+26},{dy-WALL}" fill="none" stroke="{t["rule_strong"]}" stroke-width="0.7"/>')
        o.append(rule(dx, dy - WALL, dx, dy - WALL - 26, t["rule_ink"], 1.6))
        x += w
    # corridor below the rooms, with the north arrow
    o.append(text(12, H - 8, "key plan, not to scale. the corridor is where the ideas walk in.", "mono", 9.5, t["ink4"]))
    nx, ny = W - 24, H - 13
    o.append(f'<circle cx="{nx}" cy="{ny}" r="9" fill="none" stroke="{t["rule_strong"]}" stroke-width="0.7"/>')
    o.append(f'<path d="M{nx},{ny-8} L{nx+3.5},{ny+5} L{nx},{ny+2} L{nx-3.5},{ny+5} Z" fill="{t["accent"]}"/>')
    o.append(text(nx - 16, ny + 3.5, "N", "mono-m", 9, t["ink3"], "end"))
    o.append(grain(0, 0, W, H, "kg"))
    return svg(W, H, "\n".join(o), ("mono", "mono-m"),
               "Key plan: five domains drawn as rooms, each listing the projects filed under it.")


# --------------------------------------------------------------------------
# Plate 3: the schedule of materials. Every technology, by discipline.
# --------------------------------------------------------------------------
def plate_schedule(t, stack) -> str:
    LAB_W, CH_H, GAP, PADX, ROW_GAP, SEC_PAD = 178, 24, 7, 9, 7, 16
    SIZE = 12
    layout = []
    for cat in stack:
        lines, cur, cur_w = [], [], 0.0
        for it in cat["items"]:
            w = mono_w(it["name"], SIZE) + 2 * PADX
            if cur and cur_w + GAP + w > W - (LAB_W + 12) - 12:
                lines.append(cur); cur, cur_w = [], 0.0
            cur.append((it, w)); cur_w += (GAP if cur_w else 0) + w
        if cur:
            lines.append(cur)
        layout.append((cat, lines))
    H = 1 + sum(SEC_PAD * 2 + len(l) * (CH_H + ROW_GAP) - ROW_GAP for _, l in layout) + 42
    o = [f'<defs>{grain_defs(t, "sg")}</defs>',
         f'<rect width="{W}" height="{H}" fill="{t["sheet"]}" stroke="{t["rule_strong"]}" stroke-width="1"/>']
    y = 1
    for ci, (cat, lines) in enumerate(layout):
        sec_h = SEC_PAD * 2 + len(lines) * (CH_H + ROW_GAP) - ROW_GAP
        if y > 1:
            o.append(rule(1, y, W - 1, y, t["rule"], 0.6))
        o.append(f'<rect x="1" y="{y}" width="{LAB_W-1}" height="{sec_h}" fill="{t["sunk"]}"/>')
        o.append(rule(LAB_W, y, LAB_W, y + sec_h, t["rule"], 0.6))
        words, lab_lines, cur = cat["category"].split(" "), [], ""
        for wd in words:
            trial = (cur + " " + wd).strip()
            if mono_w(trial, 9.5, 0.16) > LAB_W - 48 and cur:
                lab_lines.append(cur); cur = wd
            else:
                cur = trial
        lab_lines.append(cur)
        o.append(text(14, y + SEC_PAD + 15, f"{ci+1:02d}", "mono", 9.5, t["accent"]))
        for i, ll in enumerate(lab_lines):
            o.append(label(36, y + SEC_PAD + 16 + i * 14, ll, t, t["ink3"]))
        o.append(text(LAB_W - 12, y + sec_h - 9, f"{len(cat['items'])}", "serif", 22, t["ink4"], "end"))
        for li, line in enumerate(lines):
            cy = y + SEC_PAD + li * (CH_H + ROW_GAP)
            x = LAB_W + 12
            for it, w in line:
                heavy = it["n"] >= 3
                fill = t["accent_soft"] if heavy else "none"
                stroke = t["accent_line"] if heavy else t["rule"]
                o.append(f'<rect x="{x:.1f}" y="{cy}" width="{w:.1f}" height="{CH_H}" rx="2" fill="{fill}" stroke="{stroke}" stroke-width="0.8"/>')
                o.append(text(x + PADX, cy + 16, it["name"], "mono-m" if heavy else "mono", SIZE, t["ink"]))
                x += w + GAP
        y += sec_h
    o.append(rule(1, y, W - 1, y, t["rule_strong"], 0.8))
    ly = y + 14
    o.append(label(14, ly + 10, "legend", t))
    o.append(f'<rect x="{LAB_W+12}" y="{ly}" width="16" height="12" rx="2" fill="{t["accent_soft"]}" stroke="{t["accent_line"]}" stroke-width="0.8"/>')
    o.append(text(LAB_W + 36, ly + 10, "in three or more repositories", "mono", 10.5, t["ink3"]))
    o.append(f'<rect x="{LAB_W+262}" y="{ly}" width="16" height="12" rx="2" fill="none" stroke="{t["rule"]}" stroke-width="0.8"/>')
    o.append(text(LAB_W + 286, ly + 10, "in one or two", "mono", 10.5, t["ink3"]))
    total = sum(len(c["items"]) for c in stack)
    o.append(text(W - 14, ly + 10, f"{total} items, from every manifest I have pushed", "mono", 10.5, t["ink4"], "end"))
    o.append(grain(1, 1, W - 2, H - 2, "sg"))
    return svg(W, H, "\n".join(o), ("serif", "mono", "mono-m"),
               "Schedule of materials: every technology across my repositories, grouped by discipline.")


# --------------------------------------------------------------------------
# Plate 4: by the numbers. Counts only; no grades, no ranks.
# --------------------------------------------------------------------------
def plate_numbers(t, s, updated) -> str:
    TOP_H, PROF_H = 132, 118
    H = TOP_H + PROF_H
    o = [f'<defs>{grain_defs(t, "ng")}</defs>',
         f'<rect width="{W}" height="{H}" fill="{t["sheet"]}" stroke="{t["rule_strong"]}" stroke-width="1"/>']
    years = dt.date.today().year - int(s["active_since"])
    cells = [
        ("repositories", f'{s["repos_total"]}', f'{s["repos_public"]} public' if s["repos_total"] != s["repos_public"] else "all public", 170),
        ("contributions, last 12 months", f'{s["contributions_last_year"]}', "commits, PRs, issues, reviews", 240),
        ("on GitHub since", s["active_since"], f'{years} years of flight tests', 170),
    ]
    x = 1
    for i, (lab, val, sub, w) in enumerate(cells):
        if i:
            o.append(rule(x, 1, x, TOP_H, t["rule"], 0.6))
        o.append(label(x + 16, 26, lab, t))
        o.append(text(x + 15, 82, val, "serif", 52, t["ink"]))
        o.append(text(x + 16, 108, sub, "mono", 10.5, t["ink3"]))
        x += w
    o.append(rule(x, 1, x, TOP_H, t["rule"], 0.6))
    o.append(label(x + 16, 26, "languages, by repositories that use them", t))
    langs = [l for l in s["languages_by_repos"] if l["name"] != "Jupyter Notebook"][:7]
    mx = max(l["repos"] for l in langs)
    bar_x = x + 16 + 92
    bar_w = W - 1 - 16 - bar_x - 30
    for i, l in enumerate(langs):
        y = 38 + i * 12.5
        o.append(text(x + 16, y + 8, l["name"], "mono", 9.5, t["ink2"]))
        bw = bar_w * l["repos"] / mx
        o.append(f'<rect x="{bar_x}" y="{y}" width="{bw:.1f}" height="8" fill="{t["accent"] if i == 0 else t["accent_soft"]}" stroke="{t["accent_line"]}" stroke-width="0.6"/>')
        o.append(text(bar_x + bw + 6, y + 8, str(l["repos"]), "mono", 9.5, t["ink4"]))

    # the contribution profile: 52 weeks, drawn like a section through terrain
    o.append(rule(1, TOP_H, W - 1, TOP_H, t["rule_strong"], 0.8))
    weeks = s.get("weeks") or [0] * 52
    wk_max = max(max(weeks), 1)
    o.append(label(16, TOP_H + 24, f"contribution profile, last 52 weeks  ·  peak week {wk_max}", t))
    px0, px1 = 16, W - 16
    base = H - 26
    top = TOP_H + 36
    step = (px1 - px0) / len(weeks)
    for i in range(0, len(weeks) + 1, 4):
        xx = px0 + i * step
        o.append(rule(xx, base, xx, base + 4, t["rule"], 0.6))
    o.append(rule(px0, base, px1, base, t["rule_strong"], 0.8))
    pts = []
    for i, v in enumerate(weeks):
        xx = px0 + i * step
        hh = (base - top) * v / wk_max
        o.append(f'<rect x="{xx+1:.1f}" y="{base-hh:.1f}" width="{step-2:.1f}" height="{hh:.1f}" fill="{t["accent_soft"]}" stroke="{t["accent_line"]}" stroke-width="0.6"/>')
        pts.append(f"{xx+step/2:.1f},{base-hh:.1f}")
    o.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{t["accent"]}" stroke-width="1" stroke-linejoin="round"/>')
    o.append(text(px0, base + 16, "52 weeks ago", "mono", 9, t["ink4"]))
    o.append(text(px1, base + 16, f"this week · updated {updated}", "mono", 9, t["ink4"], "end"))
    o.append(grain(1, 1, W - 2, H - 2, "ng"))
    return svg(W, H, "\n".join(o), ("serif", "mono", "mono-m"),
               "By the numbers: repositories, contributions over the last year, years on GitHub, languages by repository count, and a 52-week contribution profile.")


# --------------------------------------------------------------------------
# Plate 5: the closing sheet, bookending the title sheet
# --------------------------------------------------------------------------
def plate_closing(t, updated, rev) -> str:
    H = 236
    TB = H - 30 - 40
    o = sheet_frame(t, H, TB)
    o.append(text(W / 2, 112, "In thrust we trust.", "serif-i", 58, t["accent"], "middle"))
    o.append(text(W / 2, 144, "Reliability is a feature. So is honesty about what isn't done yet.", "mono", 12, t["ink2"], "middle"))
    o.append(rule(30, TB, W - 30, TB, t["rule_strong"], 1))
    o.append(rule(30, TB + 3, W - 30, TB + 3, t["rule_faint"], 0.6))
    o.append(label(42, TB + 25, f"end of set  ·  sheet GH-01 of 01  ·  rev {rev}", t, t["ink3"]))
    o.append(label(W - 42, TB + 25, f"last updated {updated}", t, t["accent"], 9.5, "end"))
    o.append(grain(12, 12, W - 24, H - 24))
    return svg(W, H, "\n".join(o), ("serif-i", "mono", "mono-m"),
               f"End of set. In thrust we trust. Last updated {updated}.")


# --------------------------------------------------------------------------
# Stats: refreshed from GitHub when a token is present, else the snapshot.
# --------------------------------------------------------------------------
QUERY = """
query($login:String!){ user(login:$login){
  createdAt
  repositories(first:100, ownerAffiliations:OWNER){ totalCount nodes{ isPrivate isFork
    languages(first:12, orderBy:{field:SIZE, direction:DESC}){ edges{ size node{ name } } } } }
  contributionsCollection{ contributionCalendar{ totalContributions
    weeks{ contributionDays{ contributionCount } } } }
}}"""


def refresh_stats(login="ax5hay"):
    token = os.environ.get("GITHUB_TOKEN")
    path = DATA / "stats.json"
    if not token:
        return json.loads(path.read_text())
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
        return json.loads(path.read_text())
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
    weeks = [sum(d["contributionCount"] for d in w["contributionDays"]) for w in cal["weeks"]][-52:]
    s = {
        "generated": dt.date.today().isoformat(),
        "repos_total": u["repositories"]["totalCount"],
        "repos_public": sum(1 for n in repos if not n["isPrivate"]),
        "contributions_last_year": cal["totalContributions"],
        "active_since": u["createdAt"][:4],
        "languages_by_repos": [{"name": k, "repos": v} for k, v in cnt.most_common(12)],
        "weeks": weeks,
    }
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
    headers = [
        ("notes", "GN", "General notes", "read before the drawings", "01 / 05"),
        ("keyplan", "KP", "Key plan", "sheets filed by domain", "02 / 05"),
        ("index", "SI", "Sheet index", "numbered like the site", "03 / 05"),
        ("schedule", "SM", "Schedule of materials", "every tool, from every repo", "04 / 05"),
        ("numbers", "BN", "By the numbers", "no grades, no ranks", "05 / 05"),
    ]
    for theme, t in THEMES.items():
        out = ASSETS / theme
        out.mkdir(parents=True, exist_ok=True)
        (out / "hero.svg").write_text(plate_hero(t, stats, updated, rev))
        (out / "keyplan.svg").write_text(plate_keyplan(t, zones))
        (out / "schedule.svg").write_text(plate_schedule(t, stack))
        (out / "numbers.svg").write_text(plate_numbers(t, stats, updated))
        (out / "closing.svg").write_text(plate_closing(t, updated, rev))
        for key, code, title, note, seq in headers:
            (out / f"h-{key}.svg").write_text(plate_header(t, code, title, note, seq))
    sync_readme(stack, updated)
    print(f"updated {updated} rev {rev}: {len(list(ASSETS.glob('*/*.svg')))} plates")


if __name__ == "__main__":
    main()
