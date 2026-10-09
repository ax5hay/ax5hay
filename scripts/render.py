#!/usr/bin/env python3
"""Render the profile README's plates as SVG, in a light and a dark issue.

Everything the README shows as an image is drawn here from data/*.json, with
the site's own type (Instrument Serif, IBM Plex Mono) embedded so GitHub's
image proxy renders it the same everywhere. Standard library only.

    python scripts/render.py            # re-issue every plate
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
W = 920  # every plate shares the README column width

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
    ),
    "dark": dict(
        board="#05182a", sheet="#082139", raised="#0c2b49", sunk="#041322",
        ink="#e6f1fc", ink2="#9dbdd9", ink3="#7b9ebf", ink4="#6a8dab",
        rule_faint="rgba(157,207,255,0.12)", rule="rgba(157,207,255,0.28)",
        rule_strong="rgba(198,227,255,0.62)", rule_ink="rgba(230,241,252,0.92)",
        grid_minor="rgba(140,195,255,0.09)", grid_major="rgba(140,195,255,0.16)",
        accent="#ffc75a", accent_soft="rgba(255,199,90,0.16)",
        accent_line="rgba(255,199,90,0.7)", accent2="#6fe3a0",
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
        f'<defs><pattern id="{idp}" width="24" height="24" patternUnits="userSpaceOnUse">'
        f'<path d="M24 0H0V24" fill="none" stroke="{t["grid_minor"]}" stroke-width="0.5"/></pattern>'
        f'<pattern id="{idp}M" width="120" height="120" patternUnits="userSpaceOnUse">'
        f'<rect width="120" height="120" fill="url(#{idp})"/>'
        f'<path d="M120 0H0V120" fill="none" stroke="{t["grid_major"]}" stroke-width="0.6"/></pattern></defs>'
    )


# --------------------------------------------------------------------------
# Plate 1: the title sheet
# --------------------------------------------------------------------------
def plate_hero(t, stats, issued, rev) -> str:
    H = 468
    o = [f'<rect width="{W}" height="{H}" fill="{t["board"]}"/>']
    # the sheet, its border and its inner margin
    o.append(f'<rect x="12" y="12" width="{W-24}" height="{H-24}" fill="{t["sheet"]}" stroke="{t["rule_strong"]}" stroke-width="1"/>')
    o.append(grid_defs(t))
    o.append(f'<rect x="30" y="30" width="{W-60}" height="{H-60-52}" fill="url(#gM)"/>')
    o.append(f'<rect x="30" y="30" width="{W-60}" height="{H-60}" fill="none" stroke="{t["rule"]}" stroke-width="0.6"/>')
    # grid references along the margin, as on any drawing sheet
    cols = "ABCDEFGH"
    for i, c in enumerate(cols):
        x = 30 + (W - 60) * (i + 0.5) / len(cols)
        o.append(text(x, 24, c, "mono", 8.5, t["ink4"], "middle"))
        if i:
            xx = 30 + (W - 60) * i / len(cols)
            o.append(rule(xx, 12, xx, 18, t["rule"], 0.6))
            o.append(rule(xx, H - 18, xx, H - 12, t["rule"], 0.6))
    for i in range(4):
        y = 30 + (H - 60) * (i + 0.5) / 4
        o.append(text(21, y + 3, str(i + 1), "mono", 8.5, t["ink4"], "middle"))
        if i:
            yy = 30 + (H - 60) * i / 4
            o.append(rule(12, yy, 18, yy, t["rule"], 0.6))
            o.append(rule(W - 18, yy, W - 12, yy, t["rule"], 0.6))

    # ---- left field: the name and the thesis
    o.append(label(58, 78, "Sheet GH-01 · GitHub profile", t, t["accent"]))
    o.append(text(56, 152, "Akshay Bajpai", "serif", 72, t["ink"]))
    o.append(text(58, 200, "In thrust we trust.", "serif-i", 34, t["accent"]))
    o.append(text(58, 246, "I build reliable, robust software systems, AI or otherwise.", "mono", 13, t["ink2"]))
    o.append(text(58, 266, "The kind that holds under load, states its own assumptions,", "mono", 13, t["ink2"]))
    o.append(text(58, 286, "and fails loud instead of silent.", "mono", 13, t["ink2"]))
    o.append(label(58, 330, "AI architect  ·  forward-deployed AI engineer", t, t["ink3"]))

    # ---- right field: the engine, in section
    o.append(engine_section(t, cx=604, top=58))

    # ---- title block
    ty = H - 30 - 52
    o.append(rule(30, ty, W - 30, ty, t["rule_strong"], 1))
    cells = [
        ("drawn by", "ax5hay", 150),
        ("title", "GitHub profile", 190),
        ("sheet", "GH-01 of 01", 150),
        ("scale", "NTS", 90),
        ("issued", issued, 150),
        ("rev", str(rev), 0),
    ]
    x = 30
    for i, (lab, val, w) in enumerate(cells):
        if i:
            o.append(rule(x, ty, x, H - 30, t["rule"], 0.6))
        o.append(label(x + 12, ty + 18, lab, t))
        o.append(text(x + 12, ty + 40, val, "mono-m", 13, t["ink"]))
        x += w
    return svg(W, H, "\n".join(o), ("serif", "serif-i", "mono", "mono-m"),
               "Akshay Bajpai. In thrust we trust. Sheet GH-01, the GitHub profile title sheet.")


def engine_section(t, cx: float, top: float) -> str:
    """A thrust chamber and bell nozzle, drawn as a drafting detail.

    Thrust is the easy part; the callouts are the control surfaces that turn
    it into trust. The leaders are the sheet's one hot colour.
    """
    ink, acc = t["rule_ink"], t["accent"]
    o = []
    y0 = top
    # centreline, dash-dot, the mark of a section drawing
    o.append(rule(cx, y0 - 8, cx, y0 + 268, t["rule"], 0.6, dash="12 4 2 4"))
    # injector dome and chamber
    o.append(f'<path d="M{cx-34},{y0+22} Q{cx},{y0-4} {cx+34},{y0+22}" fill="none" stroke="{ink}" stroke-width="1.6"/>')
    o.append(f'<path d="M{cx-34},{y0+22} V{y0+80} Q{cx-34},{y0+110} {cx-13},{y0+120} '
             f'Q{cx-34},{y0+152} {cx-72},{y0+232}" fill="none" stroke="{ink}" stroke-width="1.6"/>')
    o.append(f'<path d="M{cx+34},{y0+22} V{y0+80} Q{cx+34},{y0+110} {cx+13},{y0+120} '
             f'Q{cx+34},{y0+152} {cx+72},{y0+232}" fill="none" stroke="{ink}" stroke-width="1.6"/>')
    # inner wall, a hairline offset: the cooling jacket
    o.append(f'<path d="M{cx-28},{y0+26} V{y0+78} Q{cx-28},{y0+104} {cx-9},{y0+120} '
             f'Q{cx-28},{y0+154} {cx-64},{y0+226}" fill="none" stroke="{t["rule"]}" stroke-width="0.6"/>')
    o.append(f'<path d="M{cx+28},{y0+26} V{y0+78} Q{cx+28},{y0+104} {cx+9},{y0+120} '
             f'Q{cx+28},{y0+154} {cx+64},{y0+226}" fill="none" stroke="{t["rule"]}" stroke-width="0.6"/>')
    # section hatch across the chamber wall
    for i in range(5):
        y = y0 + 34 + i * 10
        o.append(rule(cx - 34, y + 4, cx - 28, y - 2, t["rule_strong"], 0.6))
        o.append(rule(cx + 28, y + 4, cx + 34, y - 2, t["rule_strong"], 0.6))
    # exit plane and the vanes that steer the plume
    o.append(rule(cx - 72, y0 + 232, cx + 72, y0 + 232, t["rule"], 0.6, dash="3 3"))
    for s in (-1, 1):
        o.append(f'<path d="M{cx+s*20},{y0+212} L{cx+s*30},{y0+236}" stroke="{ink}" stroke-width="1.2"/>')
    # sensor tap on the bell
    o.append(f'<circle cx="{cx+50}" cy="{y0+190}" r="3" fill="none" stroke="{ink}" stroke-width="1"/>')
    # the plume: four hairlines, then thrust as a vector
    for dx in (-30, -10, 10, 30):
        o.append(rule(cx + dx * 0.6, y0 + 236, cx + dx, y0 + 262, t["rule_faint"], 0.8))
    o.append(rule(cx, y0 + 240, cx, y0 + 276, acc, 1.4))
    o.append(f'<path d="M{cx-5},{y0+270} L{cx},{y0+280} L{cx+5},{y0+270}" fill="none" stroke="{acc}" stroke-width="1.4" stroke-linejoin="miter"/>')
    o.append(text(cx + 12, y0 + 262, "thrust", "mono", 10.5, t["ink3"]))
    o.append(text(cx, y0 + 308, "Controlled, it is trust.", "serif-i", 21, acc, "middle"))

    # callouts: leader, dot at the part, label at the right
    lx = cx + 100
    callouts = [
        (cx + 34, y0 + 14, "schema that refuses bad data", y0 + 14),
        (cx + 34, y0 + 56, "orchestration", y0 + 58),
        (cx + 13, y0 + 120, "safety and guardrails", y0 + 116),
        (cx + 53, y0 + 190, "observability", y0 + 188),
    ]
    for px, py, s, ly in callouts:
        o.append(f'<circle cx="{px}" cy="{py}" r="1.8" fill="{acc}"/>')
        o.append(f'<path d="M{px},{py} L{lx-10},{ly} H{lx-4}" fill="none" stroke="{t["accent_line"]}" stroke-width="0.8"/>')
        o.append(text(lx, ly + 3.5, s, "mono", 10.5, t["ink2"]))
    # the dimension that matters
    dy = y0 + 18
    o.append(rule(cx - 34, dy - 28, cx - 34, dy - 8, t["rule"], 0.6))
    o.append(rule(cx + 34, dy - 28, cx + 34, dy - 8, t["rule"], 0.6))
    o.append(rule(cx - 34, dy - 14, cx + 34, dy - 14, t["rule_strong"], 0.6))
    for s in (-1, 1):
        o.append(f'<path d="M{cx+s*34},{dy-14} l{-s*5},-2.5 v5 z" fill="{t["rule_strong"]}"/>')
    o.append(text(cx, dy - 20, "control", "mono", 9, t["ink4"], "middle"))
    return "\n".join(o)


# --------------------------------------------------------------------------
# Section headers: a discipline code, the title, and a rule
# --------------------------------------------------------------------------
def plate_header(t, code: str, title: str, note: str = "") -> str:
    H = 58
    o = [
        text(0, 38, code, "mono-m", 12, t["accent"], tracking=0.16),
        text(44, 40, title, "serif", 32, t["ink"]),
        rule(0, 52, W, 52, t["rule_strong"], 0.8),
    ]
    if note:
        o.append(text(W, 39, note, "mono", 10.5, t["ink4"], "end"))
    return svg(W, H, "\n".join(o), ("serif", "mono", "mono-m"), title)


# --------------------------------------------------------------------------
# Plate 2: the key plan. Rooms are the domains; the names on the walls are
# the sheets filed under them.
# --------------------------------------------------------------------------
def plate_keyplan(t, zones) -> str:
    ROW_H, PAD, TOP = 34, 14, 46
    maxn = max(len(z["projects"]) for z in zones)
    H = TOP + PAD + maxn * ROW_H + 30
    # widths by the longest line each room has to hold
    widths = []
    for z in zones:
        longest = max(max(mono_w(p["name"], 13), mono_w(p["sub"], 10)) for p in z["projects"])
        widths.append(max(longest + 2 * PAD + 6, mono_w(z["title"], 9.5, 0.16) + 2 * PAD + 34))
    scale = (W - 2) / sum(widths)
    widths = [w * scale for w in widths]
    o = [f'<rect width="{W}" height="{H}" fill="{t["sheet"]}" stroke="{t["rule_strong"]}" stroke-width="1"/>']
    o.append(grid_defs(t, "k"))
    o.append(f'<rect x="1" y="1" width="{W-2}" height="{H-2}" fill="url(#kM)"/>')
    x = 1
    for z, w in zip(zones, widths):
        if x > 1:
            o.append(rule(x, 1, x, H - 1, t["rule_ink"], 1.4))
        # room tag
        o.append(f'<rect x="{x+PAD}" y="14" width="18" height="18" fill="{t["accent"]}"/>')
        o.append(text(x + PAD + 9, 27.5, z["code"], "mono-m", 11, t["sheet"], "middle"))
        o.append(label(x + PAD + 26, 27.5, z["title"], t, t["ink3"]))
        o.append(rule(x + PAD, TOP - 6, x + w - PAD, TOP - 6, t["rule"], 0.6))
        for i, p in enumerate(z["projects"]):
            y = TOP + PAD + i * ROW_H
            o.append(text(x + PAD, y + 12, p["name"], "mono-m", 13, t["ink"]))
            o.append(text(x + PAD, y + 26, p["sub"], "mono", 10, t["ink4"]))
        n = len(z["projects"])
        o.append(text(x + w - PAD, H - 12, f"{n} sheet{'s' if n != 1 else ''}", "mono", 9.5, t["ink4"], "end"))
        x += w
    return svg(W, H, "\n".join(o), ("mono", "mono-m"),
               "Key plan: five domains and the projects filed under each.")


# --------------------------------------------------------------------------
# Plate 3: the schedule of materials. Every technology, by discipline.
# --------------------------------------------------------------------------
def plate_schedule(t, stack) -> str:
    LAB_W, CH_H, GAP, PADX, ROW_GAP, SEC_PAD = 178, 24, 7, 9, 7, 16
    SIZE = 12
    rows_out, y = [], 0
    # measure first so the height is exact
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
    o = [f'<rect width="{W}" height="{H}" fill="{t["sheet"]}" stroke="{t["rule_strong"]}" stroke-width="1"/>']
    y = 1
    for cat, lines in layout:
        sec_h = SEC_PAD * 2 + len(lines) * (CH_H + ROW_GAP) - ROW_GAP
        if y > 1:
            o.append(rule(1, y, W - 1, y, t["rule"], 0.6))
        o.append(f'<rect x="1" y="{y}" width="{LAB_W-1}" height="{sec_h}" fill="{t["sunk"]}"/>')
        o.append(rule(LAB_W, y, LAB_W, y + sec_h, t["rule"], 0.6))
        # the discipline label wraps onto two lines when it has to
        words, lab_lines, cur = cat["category"].split(" "), [], ""
        for wd in words:
            trial = (cur + " " + wd).strip()
            if mono_w(trial, 9.5, 0.16) > LAB_W - 28 and cur:
                lab_lines.append(cur); cur = wd
            else:
                cur = trial
        lab_lines.append(cur)
        for i, ll in enumerate(lab_lines):
            o.append(label(14, y + SEC_PAD + 16 + i * 14, ll, t, t["ink3"]))
        n_total = len(cat["items"])
        o.append(text(14, y + sec_h - 10, f"{n_total}", "mono", 9.5, t["ink4"]))
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
    # legend
    o.append(rule(1, y, W - 1, y, t["rule_strong"], 0.8))
    ly = y + 14
    o.append(f'<rect x="{LAB_W+12}" y="{ly}" width="16" height="12" rx="2" fill="{t["accent_soft"]}" stroke="{t["accent_line"]}" stroke-width="0.8"/>')
    o.append(text(LAB_W + 36, ly + 10, "in three or more repositories", "mono", 10.5, t["ink3"]))
    o.append(f'<rect x="{LAB_W+262}" y="{ly}" width="16" height="12" rx="2" fill="none" stroke="{t["rule"]}" stroke-width="0.8"/>')
    o.append(text(LAB_W + 286, ly + 10, "in one or two", "mono", 10.5, t["ink3"]))
    total = sum(len(c["items"]) for c in stack)
    o.append(text(W - 14, ly + 10, f"{total} items, from every manifest I have pushed", "mono", 10.5, t["ink4"], "end"))
    o.append(label(14, ly + 10, "legend", t))
    return svg(W, H, "\n".join(o), ("mono", "mono-m"),
               "Schedule of materials: every technology across my repositories, grouped by discipline.")


# --------------------------------------------------------------------------
# Plate 4: by the numbers. Counts only; no grades, no ranks.
# --------------------------------------------------------------------------
def plate_numbers(t, s) -> str:
    H = 132
    o = [f'<rect width="{W}" height="{H}" fill="{t["sheet"]}" stroke="{t["rule_strong"]}" stroke-width="1"/>']
    cells = [
        ("repositories", f'{s["repos_total"]}', f'{s["repos_public"]} public' if s["repos_total"] != s["repos_public"] else "all public", 170),
        ("contributions, last 12 months", f'{s["contributions_last_year"]}', "commits, PRs, issues, reviews", 240),
        ("on GitHub since", s["active_since"], f'{dt.date.today().year - int(s["active_since"])} years of flight tests', 170),
    ]
    x = 1
    for i, (lab, val, sub, w) in enumerate(cells):
        if i:
            o.append(rule(x, 1, x, H - 1, t["rule"], 0.6))
        o.append(label(x + 16, 26, lab, t))
        o.append(text(x + 15, 82, val, "serif", 52, t["ink"]))
        o.append(text(x + 16, 108, sub, "mono", 10.5, t["ink3"]))
        x += w
    # languages, by how many repositories lean on them
    o.append(rule(x, 1, x, H - 1, t["rule"], 0.6))
    o.append(label(x + 16, 26, "languages, by repositories that use them", t))
    langs = [l for l in s["languages_by_repos"] if l["name"] not in ("Jupyter Notebook",)][:7]
    mx = max(l["repos"] for l in langs)
    bar_x = x + 16 + 92
    bar_w = W - 1 - 16 - bar_x - 30
    for i, l in enumerate(langs):
        y = 38 + i * 12.5
        o.append(text(x + 16, y + 8, l["name"], "mono", 9.5, t["ink2"]))
        bw = bar_w * l["repos"] / mx
        o.append(f'<rect x="{bar_x}" y="{y}" width="{bw:.1f}" height="8" fill="{t["accent"] if i == 0 else t["accent_soft"]}" stroke="{t["accent_line"]}" stroke-width="0.6"/>')
        o.append(text(bar_x + bw + 6, y + 8, str(l["repos"]), "mono", 9.5, t["ink4"]))
    return svg(W, H, "\n".join(o), ("serif", "mono", "mono-m"),
               "By the numbers: repositories, contributions over the last year, years on GitHub, and languages by repository count.")


# --------------------------------------------------------------------------
# Stats: refreshed from GitHub when a token is present, else the snapshot.
# --------------------------------------------------------------------------
QUERY = """
query($login:String!){ user(login:$login){
  createdAt
  repositories(first:100, ownerAffiliations:OWNER){ totalCount nodes{ isPrivate isFork
    languages(first:12, orderBy:{field:SIZE, direction:DESC}){ edges{ size node{ name } } } } }
  contributionsCollection{ contributionCalendar{ totalContributions } }
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
    s = {
        "generated": dt.date.today().isoformat(),
        "repos_total": u["repositories"]["totalCount"],
        "repos_public": sum(1 for n in repos if not n["isPrivate"]),
        "contributions_last_year": u["contributionsCollection"]["contributionCalendar"]["totalContributions"],
        "active_since": u["createdAt"][:4],
        "languages_by_repos": [{"name": k, "repos": v} for k, v in cnt.most_common(12)],
    }
    path.write_text(json.dumps(s, indent=1) + "\n")
    return s


def sync_readme(stack) -> None:
    """Keep the plain-text copy of the schedule inside README.md in step."""
    readme = ROOT / "README.md"
    if not readme.exists():
        return
    body = readme.read_text()
    start, end = "<!-- schedule:start -->", "<!-- schedule:end -->"
    if start not in body or end not in body:
        return
    lines = []
    for cat in stack:
        names = ", ".join(i["name"] for i in cat["items"])
        lines.append(f"- **{cat['category']}.** {names}")
    block = f"{start}\n" + "\n".join(lines) + f"\n{end}"
    head, rest = body.split(start, 1)
    _, tail = rest.split(end, 1)
    readme.write_text(head + block + tail)


def revision() -> int:
    try:
        return int(subprocess.check_output(["git", "rev-list", "--count", "HEAD"], cwd=ROOT, text=True).strip())
    except Exception:
        return 0


def main():
    stack = json.loads((DATA / "stack.json").read_text())
    zones = json.loads((DATA / "projects.json").read_text())["zones"]
    stats = refresh_stats()
    issued = stats.get("generated") or dt.date.today().isoformat()
    rev = revision()
    headers = [
        ("notes", "GN", "General notes", ""),
        ("keyplan", "KP", "Key plan", "sheets filed by domain"),
        ("index", "SI", "Sheet index", "numbered like the site"),
        ("schedule", "SM", "Schedule of materials", "every tool, from every repo"),
        ("numbers", "BN", "By the numbers", "no grades, no ranks"),
    ]
    for theme, t in THEMES.items():
        out = ASSETS / theme
        out.mkdir(parents=True, exist_ok=True)
        (out / "hero.svg").write_text(plate_hero(t, stats, issued, rev))
        (out / "keyplan.svg").write_text(plate_keyplan(t, zones))
        (out / "schedule.svg").write_text(plate_schedule(t, stack))
        (out / "numbers.svg").write_text(plate_numbers(t, stats))
        for key, code, title, note in headers:
            (out / f"h-{key}.svg").write_text(plate_header(t, code, title, note))
    sync_readme(stack)
    print(f"issued {issued} rev {rev}: {len(list(ASSETS.glob('*/*.svg')))} plates")


if __name__ == "__main__":
    main()
