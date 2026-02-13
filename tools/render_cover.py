#!/usr/bin/env python3
"""Generate the front and back cover HTML for one edition and screenshot them.

Usage: tools/render_cover.py --lang fa|en [--out build/fa] [--no-screenshot]

Writes <out>/cover.html and <out>/back.html. If Chrome/Chromium is available
(CHROME env var or google-chrome / chromium on PATH) it also writes
<out>/cover.png and <out>/back.png (1760x2500). Otherwise the committed
assets/cover.<lang>.png is used by the book build.

Design (original, v1.5): deep ink background; an abstract CRUSH hierarchy
(root -> zones -> racks -> hosts -> OSDs) drawn as a thin line tree, and below it a
placement-group grid in which a few PGs send three replica paths to OSDs in three
different zones. Texts come from templates/cover/cover.<lang>.yaml.
"""
import argparse, os, random, shutil, subprocess, yaml
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ap = argparse.ArgumentParser()
ap.add_argument('--lang', default='fa', choices=['fa', 'en'])
ap.add_argument('--out')
ap.add_argument('--no-screenshot', action='store_true')
A = ap.parse_args()
OUT = os.path.abspath(A.out or os.path.join(ROOT, 'build', A.lang))
os.makedirs(OUT, exist_ok=True)
T = yaml.safe_load(open(os.path.join(ROOT, 'templates', 'cover', f'cover.{A.lang}.yaml'), encoding='utf-8'))
W, H = 1760, 2500
INK, LINE, TEAL, AMBER, CORAL, MIST = '#0d1726', '#3b4d66', '#37c6b0', '#f2a541', '#ef6f6c', '#c9d6e3'
REPL = [TEAL, AMBER, CORAL]


def crush_svg(top, seed, leaf_y_off=640, grid=True, faint=1.0):
    """CRUSH-like tree + PG grid. Returns (svg, height)."""
    rnd = random.Random(seed)
    zones, racks, hosts, osds = 3, 2, 3, 3
    x0, x1 = 150, W - 150
    n_leaf = zones * racks * hosts * osds
    step = (x1 - x0) / (n_leaf - 1)
    lvl_y = [top, top + 160, top + 320, top + 480, top + leaf_y_off]
    s = []
    leaves = []

    def span(i0, i1):
        return x0 + step * (i0 + i1) / 2

    root = (W / 2, lvl_y[0])
    per_zone = racks * hosts * osds
    for z in range(zones):
        zx = span(z * per_zone, (z + 1) * per_zone - 1)
        s.append(f'<path d="M{root[0]:.1f},{root[1]:.1f} C{root[0]:.1f},{lvl_y[1] - 70:.1f} {zx:.1f},{lvl_y[0] + 70:.1f} {zx:.1f},{lvl_y[1]:.1f}" stroke="{LINE}" stroke-width="3" fill="none"/>')
        for r in range(racks):
            b = z * per_zone + r * hosts * osds
            rx = span(b, b + hosts * osds - 1)
            s.append(f'<line x1="{zx:.1f}" y1="{lvl_y[1]:.1f}" x2="{rx:.1f}" y2="{lvl_y[2]:.1f}" stroke="{LINE}" stroke-width="2.5"/>')
            for h in range(hosts):
                hb = b + h * osds
                hx = span(hb, hb + osds - 1)
                s.append(f'<line x1="{rx:.1f}" y1="{lvl_y[2]:.1f}" x2="{hx:.1f}" y2="{lvl_y[3]:.1f}" stroke="{LINE}" stroke-width="2"/>')
                for o in range(osds):
                    ox = x0 + step * (hb + o)
                    s.append(f'<line x1="{hx:.1f}" y1="{lvl_y[3]:.1f}" x2="{ox:.1f}" y2="{lvl_y[4] - 14:.1f}" stroke="{LINE}" stroke-width="1.6"/>')
                    leaves.append((ox, lvl_y[4], z))
                s.append(f'<circle cx="{hx:.1f}" cy="{lvl_y[3]:.1f}" r="7" fill="{INK}" stroke="{MIST}" stroke-opacity=".7" stroke-width="2.5"/>')
            s.append(f'<rect x="{rx - 10:.1f}" y="{lvl_y[2] - 10:.1f}" width="20" height="20" rx="4" fill="{INK}" stroke="{MIST}" stroke-opacity=".8" stroke-width="2.5"/>')
        s.append(f'<circle cx="{zx:.1f}" cy="{lvl_y[1]:.1f}" r="13" fill="{INK}" stroke="{MIST}" stroke-width="3"/>')
    s.append(f'<circle cx="{root[0]:.1f}" cy="{root[1]:.1f}" r="20" fill="{TEAL}"/><circle cx="{root[0]:.1f}" cy="{root[1]:.1f}" r="34" fill="none" stroke="{TEAL}" stroke-opacity=".35" stroke-width="3"/>')
    used = {}
    paths = []
    gtop = lvl_y[4] + 150
    cols, rows, cell, gap = 36, 5, 30, 11.4
    gw = cols * cell + (cols - 1) * gap
    gx0 = (W - gw) / 2
    if grid:
        hot = rnd.sample(range(cols * rows), 7)
        for k in range(cols * rows):
            c, r = k % cols, k // cols
            x, y = gx0 + c * (cell + gap), gtop + r * (cell + gap)
            if k in hot:
                fill = f'fill="{MIST}" fill-opacity=".95"'
                # three replicas in three different zones
                tgt = []
                for z in rnd.sample(range(zones), 3):
                    cand = [i for i, l in enumerate(leaves) if l[2] == z]
                    tgt.append(rnd.choice(cand))
                for j, i in enumerate(tgt):
                    lx, ly, _ = leaves[i]
                    px, py = x + cell / 2, y
                    paths.append(f'<path d="M{px:.1f},{py:.1f} C{px:.1f},{py - 90:.1f} {lx:.1f},{ly + 110:.1f} {lx:.1f},{ly + 16:.1f}" stroke="{REPL[j]}" stroke-opacity="{.75 * faint:.2f}" stroke-width="2.6" fill="none"/>')
                    used[i] = REPL[j]
            else:
                op = rnd.choice([.10, .14, .18, .24])
                fill = f'fill="{MIST}" fill-opacity="{op * faint:.2f}"'
            s.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell}" height="{cell}" rx="5" {fill}/>')
    for i, (lx, ly, _) in enumerate(leaves):
        col = used.get(i)
        if col:
            s.append(f'<rect x="{lx - 11:.1f}" y="{ly - 11:.1f}" width="22" height="22" rx="5" fill="{col}"/>')
        else:
            s.append(f'<rect x="{lx - 9:.1f}" y="{ly - 9:.1f}" width="18" height="18" rx="4" fill="none" stroke="{MIST}" stroke-opacity=".55" stroke-width="2"/>')
    height = (gtop + rows * (cell + gap) if grid else lvl_y[4] + 30) - top + 40
    return ''.join(paths) + ''.join(s), height


BASE = f'''html,body{{margin:0;width:{W}px;height:{H}px;overflow:hidden}}
body{{font-family:{T["font"]};direction:{T["dir"]};position:relative;color:#fff;
background:radial-gradient(1400px 1100px at {"85%" if T["dir"] == "rtl" else "15%"} 8%,#1b2d47 0%,{INK} 62%) ,{INK}}}
.en{{font-family:Inter,'DejaVu Sans',sans-serif;direction:ltr;unicode-bidi:isolate}}
svg{{position:absolute;left:0}}
'''
side, oside = T['side'], T['oside']
art, art_h = crush_svg(0, 5)
ART_TOP = 1090
front = f'''<!doctype html><html><head><meta charset="utf-8"><style>{BASE}
.top{{position:absolute;top:170px;{side}:150px;{oside}:150px}}
.kick{{display:flex;align-items:center;gap:22px;font-size:36px;font-weight:600;color:{TEAL};letter-spacing:{"0" if T["dir"] == "rtl" else "4px"};{"" if T["dir"] == "rtl" else "text-transform:uppercase;"}}}
.kick i{{display:inline-block;width:80px;height:6px;background:{TEAL};border-radius:3px}}
h1{{font-size:{T.get("title_size", 150)}px;font-weight:800;line-height:1.18;margin:56px 0 0;letter-spacing:{"0" if T["dir"] == "rtl" else "-3px"}}}
h1 .en{{color:{TEAL}}}
.sub{{font-size:50px;font-weight:300;margin-top:48px;color:{MIST};line-height:1.5}}
.sub b{{font-weight:600;color:#fff}}
.legend{{position:absolute;top:{ART_TOP + art_h - 30}px;{side}:150px;font-size:26px;color:#8ea2ba;letter-spacing:.5px}}
.legend .en{{font-size:26px}}
.foot{{position:absolute;bottom:150px;{side}:150px;{oside}:150px;display:flex;justify-content:space-between;align-items:flex-end;border-top:2px solid {LINE};padding-top:50px}}
.auth{{font-size:64px;font-weight:700}}
.ed{{font-size:32px;color:#8ea2ba;text-align:{oside};line-height:1.6}}
.lic{{position:absolute;bottom:80px;{side}:150px;font-size:24px;color:#6f849e}}
</style></head><body>
<div class="top"><div class="kick"><i></i>{T["kicker"]}</div>
<h1>{T["title_html"]}</h1>
<div class="sub">{T["subtitle_html"]}</div></div>
<svg style="top:{ART_TOP}px" width="{W}" height="{art_h}" viewBox="0 0 {W} {art_h}">{art}</svg>
<div class="legend">{T["legend_html"]}</div>
<div class="foot"><div class="auth">{T["author"]}</div><div class="ed">{T["edition_html"]}</div></div>
<div class="lic">{T["tagline"]}</div>
</body></html>'''
_r = random.Random(3)
STRIP = ''.join('<i class="%s"></i>' % _r.choice(['', '', '', '', '', '', 't', 'a', 'c']) for _ in range(40))
backc = f'''<!doctype html><html><head><meta charset="utf-8"><style>{BASE}
.box{{position:absolute;top:220px;right:150px;left:150px;font-size:42px;line-height:1.9;text-align:justify;color:{MIST};font-weight:300}}
.box h2{{font-size:70px;font-weight:800;color:#fff;margin:0 0 46px}}
.box h2::before{{content:"";display:block;width:80px;height:6px;background:{TEAL};border-radius:3px;margin-bottom:40px}}
.box ul{{padding-{side}:46px;margin:28px 0}}.box li{{margin-bottom:10px}}.box li::marker{{color:{TEAL}}}
.strip{{position:absolute;bottom:330px;right:150px;left:150px;height:14px;display:flex;gap:10px}}.strip i{{flex:1;border-radius:3px;background:{MIST};opacity:.14}}.strip i.h{{opacity:.9}}.strip i.t{{background:{TEAL};opacity:.9}}.strip i.a{{background:{AMBER};opacity:.9}}.strip i.c{{background:{CORAL};opacity:.9}}
.note{{position:absolute;bottom:130px;right:150px;left:150px;font-size:30px;color:#8ea2ba;line-height:1.8;border-top:2px solid {LINE};padding-top:36px;text-align:{side}}}
</style></head><body>
<div class="box"><h2>{T["back_title"]}</h2>
{T["back_body_html"]}</div>
<div class="strip">{STRIP}</div>
<div class="note">{T["back_note_html"]}</div>
</body></html>'''

open(os.path.join(OUT, 'cover.html'), 'w', encoding='utf-8').write(front)
open(os.path.join(OUT, 'back.html'), 'w', encoding='utf-8').write(backc)
chrome = os.environ.get('CHROME') or shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chromium-browser')
if chrome and not A.no_screenshot:
    for n in ('cover', 'back'):
        subprocess.run([chrome, '--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars', f'--window-size={W},{H}',
                        f'--screenshot={OUT}/{n}.png', f'file://{OUT}/{n}.html'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print('cover: rendered', OUT)
else:
    print('cover: html only (no chrome); using assets/cover.%s.png' % A.lang)
