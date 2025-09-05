#!/usr/bin/env python3
"""Render high-resolution figure variants for the web edition (not committed).

The committed PNGs are sized for print (<=1800 px, 64 colours). For the web
book's zoom, this script writes sharper variants into build/webfig/, mirroring
figures/:

* Mermaid  figures/chNN/x[.en].mmd  -> x[.en].webp at 3x device scale
* byte-layout figures  x.bf.json    -> x.webp at 2x device scale
* Matplotlib plots (figures/scripts/plot_*.py) -> x.svg (vector, text as paths)

Plot scripts run in a scratch copy of figures/ so nothing in the repository is
touched. Scripts run in name order and a later script wins, matching how the
committed PNGs were produced; an SVG whose aspect ratio does not match the
committed PNG is discarded. Results are cached by content hash in
build/webfig/manifest.json, so only changed sources are re-rendered.

Usage: tools/render_web_figures.py [--out build/webfig] [--jobs 4] [--force]
Environment: MMDC, CHROME (as for render_figures.py)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageChops

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_bytefig  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
FIG = os.path.join(ROOT, 'figures')
ap = argparse.ArgumentParser()
ap.add_argument('--out', default=os.path.join(ROOT, 'build', 'webfig'))
ap.add_argument('--jobs', type=int, default=4)
ap.add_argument('--force', action='store_true')
a = ap.parse_args()
OUT = os.path.abspath(a.out)
os.makedirs(OUT, exist_ok=True)
MAN = os.path.join(OUT, 'manifest.json')
man = json.load(open(MAN)) if os.path.exists(MAN) and not a.force else {}
mmdc = os.environ.get('MMDC') or shutil.which('mmdc') or os.path.join(ROOT, 'node_modules', '.bin', 'mmdc')
chrome = os.environ.get('CHROME') or shutil.which('google-chrome') or shutil.which('chromium')


def h(*paths):
    d = hashlib.sha256()
    for p in paths:
        d.update(open(p, 'rb').read())
    return d.hexdigest()


def out_for(src, ext):
    rel = os.path.relpath(src, FIG)
    for suf in ('.bf.json', '.mmd', '.png'):
        if rel.endswith(suf):
            rel = rel[:-len(suf)]
    p = os.path.join(OUT, rel + ext)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def to_webp(png, dst, cap=5400):
    im = Image.open(png).convert('RGB')
    if im.width > cap:
        im = im.resize((cap, int(im.height * cap / im.width)), Image.LANCZOS)
    im.save(dst, 'WEBP', quality=90, method=5)


pp = json.load(open(os.path.join(FIG, 'mermaid', 'puppeteer.json')))
if chrome:
    pp['executablePath'] = chrome
ppf = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
json.dump(pp, ppf)
ppf.close()
CONF = [os.path.join(FIG, 'mermaid', f) for f in sorted(os.listdir(os.path.join(FIG, 'mermaid')))]


def mermaid(src):
    key = h(src, *CONF) + ':3x'
    dst = out_for(src, '.webp')
    rel = os.path.relpath(src, ROOT)
    if man.get(rel) == key and os.path.exists(dst):
        return rel, None, False
    lang = src.rsplit('.', 2)[-2] if src.count('.') >= 2 else ''
    sfx = '.en' if lang == 'en' else ''
    with tempfile.TemporaryDirectory() as td:
        png = os.path.join(td, 'f.png')
        r = subprocess.run([mmdc, '-i', src, '-o', png, '-c', os.path.join(FIG, 'mermaid', f'config{sfx}.json'),
                            '-C', os.path.join(FIG, 'mermaid', f'theme{sfx}.css'), '-s', '3', '-b', 'white', '-p', ppf.name],
                           capture_output=True, text=True, timeout=240)
        if r.returncode or not os.path.exists(png):
            return rel, 'FAIL ' + r.stderr.strip()[-200:], False
        to_webp(png, dst)
    return rel, key, True


def bytefig(src):
    key = h(src, os.path.join(ROOT, 'tools', 'render_bytefig.py')) + ':2x'
    dst = out_for(src, '.webp')
    rel = os.path.relpath(src, ROOT)
    if man.get(rel) == key and os.path.exists(dst):
        return rel, None, False
    spec = json.load(open(src, encoding='utf-8'))
    W = spec.get('width', 1700)
    with tempfile.TemporaryDirectory() as td:
        page, png = os.path.join(td, 'f.html'), os.path.join(td, 'f.png')
        open(page, 'w', encoding='utf-8').write(render_bytefig.build(spec))
        subprocess.run([render_bytefig.CHROME, '--headless', '--no-sandbox', '--disable-gpu', '--hide-scrollbars',
                        '--force-device-scale-factor=2', f'--window-size={W},4000', f'--screenshot={png}', 'file://' + page],
                       capture_output=True, timeout=120)
        im = Image.open(png).convert('RGB')
        bb = ImageChops.difference(im, Image.new('RGB', im.size, 'white')).getbbox()
        if bb:
            im = im.crop((0, 0, im.width, min(im.height, bb[3] + 48)))
        im.save(png)
        to_webp(png, dst)
    return rel, key, True


jobs = sorted(glob.glob(os.path.join(FIG, 'ch[0-9][0-9]', '*.mmd')))
bfs = sorted(glob.glob(os.path.join(FIG, 'ch[0-9][0-9]', '*.bf.json')))
done = failed = 0
with cf.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
    for rel, key, new in ex.map(mermaid, jobs):
        if key and key.startswith('FAIL'):
            failed += 1
            print('render_web_figures:', rel, key)
        elif key:
            man[rel] = key
            done += new
for src in bfs:
    rel, key, new = bytefig(src)
    if key:
        man[rel] = key
        done += new
os.unlink(ppf.name)

# ---- Matplotlib plots -> SVG (scratch copy, savefig redirected) ----
SCRIPTS = sorted(glob.glob(os.path.join(FIG, 'scripts', 'plot_*.py')))
DATA = sorted(p for p in glob.glob(os.path.join(FIG, 'data', '**', '*'), recursive=True) if os.path.isfile(p))
skey = h(*SCRIPTS, *sorted(glob.glob(os.path.join(FIG, 'scripts', 'lib', '*.py'))), *DATA)
svg_n = 0
if man.get('plots') != skey or a.force:
    with tempfile.TemporaryDirectory() as td:
        shutil.copytree(os.path.join(FIG, 'scripts'), os.path.join(td, 'figures', 'scripts'))
        if os.path.isdir(os.path.join(FIG, 'data')):
            shutil.copytree(os.path.join(FIG, 'data'), os.path.join(td, 'figures', 'data'))
        for d in glob.glob(os.path.join(FIG, 'ch[0-9][0-9]')):
            os.makedirs(os.path.join(td, 'figures', os.path.basename(d)), exist_ok=True)
        svgdir = os.path.join(td, 'svg')
        wrapper = f'''
import os, sys, runpy, matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["svg.fonttype"] = "path"
matplotlib.rcParams["svg.hashsalt"] = "book"
import matplotlib.figure as mf
FIGDIR = os.path.abspath("figures"); SVG = {svgdir!r}
orig = mf.Figure.savefig
def savefig(self, fname, *args, **kw):
    p = os.path.abspath(str(fname))
    if p.endswith(".png") and p.startswith(FIGDIR + os.sep):
        out = os.path.join(SVG, os.path.relpath(p, FIGDIR)[:-4] + ".svg")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        kw.pop("dpi", None); kw["format"] = "svg"; kw.setdefault("metadata", {{"Date": None}})
        return orig(self, out, *args, **kw)
    return orig(self, fname, *args, **kw)
mf.Figure.savefig = savefig
script = sys.argv[1]
sys.argv = [script]
sys.path.insert(0, os.path.dirname(script))
runpy.run_path(script, run_name="__main__")
'''
        for s in SCRIPTS:
            r = subprocess.run([sys.executable, '-c', wrapper, os.path.join(td, 'figures', 'scripts', os.path.basename(s))],
                               cwd=td, capture_output=True, text=True, timeout=300, env=dict(os.environ, MPLBACKEND='Agg'))
            if r.returncode:
                print('render_web_figures: plot script failed (PNG fallback):', os.path.basename(s), r.stderr.strip().splitlines()[-1:] or '')
        for svg in glob.glob(os.path.join(svgdir, '**', '*.svg'), recursive=True):
            rel = os.path.relpath(svg, svgdir)
            png = os.path.join(FIG, rel[:-4] + '.png')
            if not os.path.exists(png):
                continue
            t = open(svg, encoding='utf-8').read(2000)
            m = re.search(r'width="([\d.]+)pt" height="([\d.]+)pt"', t)
            pw, ph = Image.open(png).size
            if not m or abs(float(m.group(1)) / float(m.group(2)) - pw / ph) > 0.03 * (pw / ph):
                print('render_web_figures: aspect mismatch, keeping PNG:', rel)
                continue
            dst = os.path.join(OUT, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(svg, dst)
            svg_n += 1
    man['plots'] = skey
json.dump(dict(sorted(man.items())), open(MAN, 'w'), indent=1)
print(f'render_web_figures: {done} raster variants rendered, {svg_n} SVG plots, {failed} failed')
sys.exit(1 if failed else 0)
