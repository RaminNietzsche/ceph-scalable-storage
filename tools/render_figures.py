#!/usr/bin/env python3
"""Render figure sources to PNG, incrementally (only when the source is newer).

* figures/chNN/*.mmd           Mermaid diagrams (Persian labels)  -> *.png
* figures/chNN/*.<lang>.mmd    generated language variants        -> *.<lang>.png
* figures/chNN/*.bf.json       byte-layout specs (render_bytefig) -> *.png
Raster outputs are downscaled to <=1800 px wide and quantised to 64 colours.

Usage: tools/render_figures.py [--lang en] [--force] [chNN ...]
Environment: MMDC (mermaid-cli binary), CHROME (browser for puppeteer)
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_bytefig  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
FIG = os.path.join(ROOT, 'figures')
ap = argparse.ArgumentParser()
ap.add_argument('--force', action='store_true')
ap.add_argument('chapters', nargs='*')
a = ap.parse_args()
dirs = [os.path.join(FIG, c) for c in a.chapters] or sorted(glob.glob(os.path.join(FIG, 'ch[0-9][0-9]')))
mmdc = os.environ.get('MMDC') or shutil.which('mmdc') or os.path.join(ROOT, 'node_modules', '.bin', 'mmdc')
chrome = os.environ.get('CHROME') or shutil.which('google-chrome') or shutil.which('chromium')
pp = json.load(open(os.path.join(FIG, 'mermaid', 'puppeteer.json')))
if chrome:
    pp['executablePath'] = chrome
else:
    pp.pop('executablePath', None)
ppf = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
json.dump(pp, ppf)
ppf.close()


MANIFEST = os.path.join(FIG, 'render-manifest.json')
man = json.load(open(MANIFEST)) if os.path.exists(MANIFEST) else {}


def digest(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def stale(src, out):
    """Content-hash based (git does not preserve mtimes)."""
    rel = os.path.relpath(src, ROOT)
    return a.force or not os.path.exists(out) or man.get(rel) != digest(src)


def mark(src):
    man[os.path.relpath(src, ROOT)] = digest(src)


def finish(png):
    im = Image.open(png)
    if im.mode == 'P':
        return
    im = im.convert('RGB')
    if im.width > 1800:
        im = im.resize((1800, int(im.height * 1800 / im.width)), Image.LANCZOS)
    im.quantize(colors=64, method=Image.Quantize.MEDIANCUT).save(png, optimize=True)


done = failed = 0
for d in dirs:
    for src in sorted(glob.glob(os.path.join(d, '*.mmd'))):
        out = src[:-4] + '.png'
        if not stale(src, out):
            continue
        lang = src.rsplit('.', 2)[-2] if src.count('.') >= 2 else ''
        sfx = f'.{lang}' if lang in ('en',) else ''
        r = subprocess.run([mmdc, '-i', src, '-o', out, '-c', os.path.join(FIG, 'mermaid', f'config{sfx}.json'),
                            '-C', os.path.join(FIG, 'mermaid', f'theme{sfx}.css'), '-s', '2', '-b', 'white', '-p', ppf.name],
                           capture_output=True, text=True, timeout=180)
        if r.returncode:
            failed += 1
            print('FAIL', os.path.relpath(src, ROOT), r.stderr.strip()[-300:])
            continue
        finish(out)
        mark(src)
        done += 1
        print('mermaid', os.path.relpath(out, ROOT))
    for src in sorted(glob.glob(os.path.join(d, '*.bf.json'))):
        out = src[:-8] + '.png'
        if not stale(src, out):
            continue
        spec = json.load(open(src, encoding='utf-8'))
        render_bytefig.shot(render_bytefig.build(spec), out, spec.get('width', 1700))
        mark(src)
        done += 1
        print('bytefig', os.path.relpath(out, ROOT))
os.unlink(ppf.name)
json.dump(dict(sorted(man.items())), open(MANIFEST, 'w'), indent=1)
print(f'render_figures: {done} rendered, {failed} failed')
sys.exit(1 if failed else 0)
