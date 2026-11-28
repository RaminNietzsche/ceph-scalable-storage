#!/usr/bin/env python3
"""Render the badge art of the web edition from references/badges.yaml.

Writes one JavaScript asset: window.__BADGES__ (SVG <defs> with the tier metals, category
fields, frame clip paths and one <symbol> per glyph, plus the frame shapes and the badge table)
followed by the renderer in templates/site/badges.js. tools/build_site.py calls write_asset();
templates/site/game.js draws every badge with BadgeArt.svg().

Usage:
  tools/render_badges.py --out build/badges/badges.js
  tools/render_badges.py --sheet build/badges/sheet-dark.html --theme dark [--locked]
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DATA = os.path.join(ROOT, 'references', 'badges.yaml')
RENDERER = os.path.join(ROOT, 'templates', 'site', 'badges.js')
NUM = r'-?\d*\.?\d+'


def load(path: str = DATA) -> dict:
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def _f(x: float) -> str:
    s = f'{x:.2f}'.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def poly(points) -> str:
    return 'M' + 'L'.join(f'{_f(x)} {_f(y)}' for x, y in points) + 'Z'


def hexagon(cx: float, cy: float, r: float) -> list:
    return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in range(-90, 270, 60)]


def gear(cx: float, cy: float, r_out: float, r_in: float, teeth: int) -> str:
    pts = []
    for i in range(teeth * 4):
        a = 2 * math.pi * i / (teeth * 4) - math.pi / 2
        r = r_out if i % 4 in (1, 2) else r_in
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return poly(pts)


def circle_path(cx: float, cy: float, r: float) -> str:
    return f'M{_f(cx - r)} {_f(cy)}a{_f(r)} {_f(r)} 0 1 0 {_f(2 * r)} 0a{_f(r)} {_f(r)} 0 1 0 {_f(-2 * r)} 0Z'


# Frame shapes on a 64 x 64 canvas: rim, field, glyph box [x, y, size], gloss centre, lock spot, ribbon/banner.
SHAPES = {
    'hex': {'rim': poly(hexagon(32, 30, 28)), 'field': poly(hexagon(32, 30, 22.5)), 'g': [18.5, 16, 27], 'gloss': 14,
            'lock': [51, 13], 'banner': 'M10 48h44l-3.8 5.2L54 58.4H10l3.8-5.2Z'},
    'gem': {'rim': poly([(32, 2.5), (60.5, 31), (32, 59.5), (3.5, 31)]), 'field': poly([(32, 9.5), (53.5, 31), (32, 52.5), (10.5, 31)]),
            'g': [20, 19, 24], 'gloss': 16, 'lock': [50, 49]},
    'medal': {'rim': gear(32, 28, 26.5, 24, 18), 'field': circle_path(32, 28, 19.5), 'g': [19, 15, 26], 'gloss': 14,
              'lock': [50, 46], 'tails': 'M22 40 15.5 62.5l6.8-3.6L27 63.5 31 45ZM42 40l6.5 22.5-6.8-3.6L37 63.5 33 45Z'},
}

GLYPH_RE = re.compile(r'^([pfcdrb]):(.+)$')
F = ' fill="currentColor" stroke="none"'


def glyph_svg(items: list) -> str:
    """The glyph mini-language (see references/badges.yaml) to SVG elements."""
    out = []
    for it in items:
        m = GLYPH_RE.match(it)
        if not m:
            raise ValueError(f'bad glyph item: {it!r}')
        k, v = m.groups()
        if k in 'pf':
            if not re.fullmatch(r'[MmLlHhVvCcSsQqTtAaZz0-9 ,.\-]+', v):
                raise ValueError(f'bad path data: {v!r}')
            out.append(f'<path d="{v}"' + (F if k == 'f' else '') + '/>')
        else:
            n = [float(x) for x in v.split(',')]
            if k in 'cd':
                if len(n) != 3:
                    raise ValueError(f'circle needs cx,cy,r: {it!r}')
                out.append(f'<circle cx="{_f(n[0])}" cy="{_f(n[1])}" r="{_f(n[2])}"' + (F if k == 'd' else '') + '/>')
            else:
                if len(n) != 5:
                    raise ValueError(f'rect needs x,y,w,h,rx: {it!r}')
                out.append(f'<rect x="{_f(n[0])}" y="{_f(n[1])}" width="{_f(n[2])}" height="{_f(n[3])}" rx="{_f(n[4])}"' + (F if k == 'b' else '') + '/>')
    return ''.join(out)


def glyph_bounds(items: list) -> tuple:
    """Rough extent of a glyph (every number pair in its coordinates); used by the validator."""
    xs, ys = [], []
    for it in items:
        k, v = GLYPH_RE.match(it).groups()
        if k in 'cd':
            cx, cy, r = (float(x) for x in v.split(','))
            xs += [cx - r, cx + r]
            ys += [cy - r, cy + r]
        elif k in 'rb':
            x, y, w, h, _ = (float(x) for x in v.split(','))
            xs += [x, x + w]
            ys += [y, y + h]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def grad(id_: str, stops: list, kind: str = 'linear', var: str | None = None) -> str:
    n = len(stops)
    st = []
    for i, c in enumerate(stops):
        off = _f(i / (n - 1)) if n > 1 else '0'
        col = f'var(--{var}{i + 1},{c})' if var else c
        st.append(f'<stop offset="{off}" style="stop-color:{col}"/>' if var else f'<stop offset="{off}" stop-color="{c}"/>')
    if kind == 'radial':
        return f'<radialGradient id="{id_}" cx=".35" cy=".25" r=".9">{"".join(st)}</radialGradient>'
    return f'<linearGradient id="{id_}" x1=".15" y1="0" x2=".85" y2="1">{"".join(st)}</linearGradient>'


def defs(d: dict) -> str:
    parts = []
    for t in (1, 2, 3):
        parts.append(grad(f'bdg-m{t}', d['metals'][t]))
    parts.append(grad('bdg-mh', d['metals']['holo']))
    parts.append(grad('bdg-ml', ['#e2e8f0', '#b6c0cd', '#8592a5'], var='bdg-l'))   # locked rim, themed by CSS
    for cid, c in d['categories'].items():
        parts.append(grad(f'bdg-f-{cid}', c['field'], 'radial'))
    parts.append(grad('bdg-fl', ['#cbd5e1', '#64748b'], 'radial', var='bdg-lf'))   # locked field
    parts.append('<linearGradient id="bdg-sh" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
                 '<stop offset=".5" stop-color="#fff" stop-opacity=".75"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>')
    for name, sh in SHAPES.items():
        parts.append(f'<clipPath id="bdg-k-{name}"><path d="{sh["field"]}"/></clipPath>')
    sym = {'lock': d['glyphs']['lock'], 'secret': d['glyphs']['secret']}
    for b in d['badges']:
        sym[b['id']] = b['glyph']
    for k, items in sym.items():
        parts.append(f'<symbol id="bdg-g-{k}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">{glyph_svg(items)}</symbol>')
    return ('<svg id="bdg-defs" class="bdg-defs" width="0" height="0" aria-hidden="true" focusable="false" '
            'style="position:absolute;width:0;height:0;overflow:hidden"><defs>' + ''.join(parts) + '</defs></svg>')


def data_js(d: dict) -> str:
    cats = {cid: {'s': c['shape'], 'a': c['accent']} for cid, c in d['categories'].items()}
    table = {b['id']: {'c': b['cat'], 't': b['tier'], 'h': 1 if b.get('hidden') else 0} for b in d['badges']}
    payload = {'v': d['version'], 'defs': defs(d), 'shapes': SHAPES, 'cats': cats, 'order': list(d['categories']),
               'ids': [b['id'] for b in d['badges']], 'b': table}
    return 'window.__BADGES__=' + json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + ';\n'


def asset_js(d: dict | None = None) -> str:
    d = d or load()
    with open(RENDERER, encoding='utf-8') as f:
        return '/* generated by tools/render_badges.py from references/badges.yaml; do not edit */\n' + data_js(d) + f.read()


def write_asset(dest_dir: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    out = os.path.join(dest_dir, 'badges.js')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(asset_js())
    return out


def sheet(d: dict, theme: str, locked: bool, css: str) -> str:
    """A stand-alone preview page with every badge (for screenshots and design review)."""
    names = {}
    gy = os.path.join(ROOT, 'templates', 'site', 'game.yaml')
    if os.path.exists(gy):
        names = yaml.safe_load(open(gy, encoding='utf-8'))['en']['badges']
    cells = []
    for b in d['badges']:
        nm = names.get(b['id'], [b['id']])[0]
        cells.append(f'<figure data-id="{b["id"]}" data-tier="{b["tier"]}" data-hidden="{1 if b.get("hidden") else 0}"><span class="art"></span>'
                     f'<figcaption>{html.escape(nm)}</figcaption></figure>')
    js = asset_js(d)
    bg = '#0b1120' if theme == 'dark' else '#f8fafc'
    fg = '#e2e8f0' if theme == 'dark' else '#0f172a'
    return f"""<!doctype html><html lang="en" data-theme="{theme}"><head><meta charset="utf-8"><title>Badges</title>
<style>{css}
body {{ margin: 0; padding: 28px; background: {bg}; color: {fg}; font: 13px/1.35 Inter, system-ui, sans-serif; }}
h1 {{ font-size: 18px; margin: 0 0 18px; font-weight: 650; }}
.grid {{ display: grid; grid-template-columns: repeat(9, 112px); gap: 14px 10px; }}
figure {{ margin: 0; display: flex; flex-direction: column; align-items: center; gap: 6px; text-align: center; }}
figure .bdg {{ width: 76px; height: 76px; }}
figcaption {{ font-size: 11.5px; opacity: .85; }}
</style></head><body><h1>{'Locked' if locked else 'All 52 badges'}, {theme} theme</h1><div class="grid">{''.join(cells)}</div>
<script>{js}</script><script>
document.querySelectorAll('figure').forEach(function (f) {{
  var t = f.dataset.tier === 'tiered' ? 3 : +f.dataset.tier, locked = {str(locked).lower()};
  f.querySelector('.art').innerHTML = BadgeArt.svg(f.dataset.id, locked ? 0 : t, {{ hidden: locked && f.dataset.hidden === '1' }});
}});
</script></body></html>"""


def badge_css() -> str:
    """The badge rules of templates/site/site.css (between the BADGE-ART markers), for the preview sheet."""
    css = open(os.path.join(ROOT, 'templates', 'site', 'site.css'), encoding='utf-8').read()
    m = re.search(r'/\* BADGE-ART \*/(.*?)/\* /BADGE-ART \*/', css, re.S)
    return m.group(1) if m else ''


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', help='write the badges.js asset to this path')
    ap.add_argument('--sheet', help='write a preview HTML page with every badge')
    ap.add_argument('--theme', choices=('light', 'dark'), default='light')
    ap.add_argument('--locked', action='store_true', help='draw the sheet in the locked state')
    a = ap.parse_args()
    d = load()
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        open(a.out, 'w', encoding='utf-8').write(asset_js(d))
        print(f'render_badges: {len(d["badges"])} badges -> {a.out}')
    if a.sheet:
        os.makedirs(os.path.dirname(os.path.abspath(a.sheet)), exist_ok=True)
        open(a.sheet, 'w', encoding='utf-8').write(sheet(d, a.theme, a.locked, badge_css()))
        print(f'render_badges: sheet -> {a.sheet}')
    if not (a.out or a.sheet):
        ap.error('nothing to do: give --out and/or --sheet')


if __name__ == '__main__':
    main()
