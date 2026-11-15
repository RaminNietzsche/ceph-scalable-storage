#!/usr/bin/env python3
"""Render build/<lang>/book.html to PDF with WeasyPrint in two passes.

Pass 1 lays out the book to learn the page of every index anchor; pass 2
fills the index with those page numbers and verifies that no anchor moved.
Exit status is non-zero if any index reference points to the wrong page.

Usage: tools/render_pdf.py --lang fa|en [--build build/fa] [--out file.pdf]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys

import yaml
from weasyprint import HTML

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ap = argparse.ArgumentParser()
ap.add_argument('--lang', default='fa', choices=['fa', 'en'])
ap.add_argument('--build', default=None)
ap.add_argument('--out', default=None)
a = ap.parse_args()
B = os.path.abspath(a.build or os.path.join(ROOT, 'build', a.lang))
UI = yaml.safe_load(open(os.path.join(ROOT, 'content', a.lang, 'ui.yaml'), encoding='utf-8'))
META = yaml.safe_load(open(os.path.join(ROOT, 'content', a.lang, 'metadata.yaml'), encoding='utf-8'))
OUT = a.out or os.path.join(B, META['outputs']['pdf'])
FA = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹') if UI['digits'] == 'fa' else str.maketrans('', '')
SEP = UI['list_sep']
src = open(os.path.join(B, 'book.html'), encoding='utf-8').read()
# KaTeX emits HTML + a visually hidden MathML copy; print keeps only the typeset HTML
# (otherwise every formula would be extracted twice from the PDF text layer).
src = re.sub(r'<span class="katex-mathml">.*?</math></span>', '', src, flags=re.S)
hits = json.load(open(os.path.join(B, 'ix_hits.json'), encoding='utf-8'))


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;')


def build_index(pages):
    out = []
    cur = None
    for t in sorted(hits, key=lambda x: x.lower()):
        bych = collections.OrderedDict()
        for c, anchor in hits[t]:
            p = pages.get(anchor)
            if p is None:
                continue
            bych.setdefault(c, [])
            if p not in bych[c]:
                bych[c].append(p)
        ps = []
        for c, lst in bych.items():
            ps += sorted(lst)[:2]
        ps = sorted(set(ps))[:20]
        if not ps:
            continue
        letter = t[0].upper()
        if letter != cur:
            cur = letter
            out.append(f'<div class="ixl">{letter}</div>')
        out.append(f'<div class="ixe"><span class="en">{esc(t)}</span> <span class="ixp">{SEP.join(str(p).translate(FA) for p in ps)}</span></div>')
    return ''.join(out)


def anchors(doc):
    m = {}
    ch1 = None
    for i, pg in enumerate(doc.pages):
        for anchor in pg.anchors:
            if anchor not in m:
                m[anchor] = i
            if anchor == 'ch1' and ch1 is None:
                ch1 = i
    return m, ch1


def render(html):
    return HTML(string=html, base_url=ROOT).render()


d = render(src.replace('<!--INDEX-->', build_index({})))
m, ch1 = anchors(d)
print('pass1', len(d.pages), 'ch1', ch1, flush=True)
pages = {k: i - ch1 + 1 for k, i in m.items() if k.startswith('ix')}
d2 = render(src.replace('<!--INDEX-->', build_index(pages)))
m2, _ = anchors(d2)
bad = sum(1 for k in pages if m2.get(k, -1) - ch1 + 1 != pages[k])
print('pass2', len(d2.pages), 'mismatch', bad, flush=True)
d2.write_pdf(OUT)
json.dump({'pages': len(d2.pages), 'index_mismatch': bad, 'pdf': os.path.relpath(OUT, ROOT)}, open(os.path.join(B, 'render.json'), 'w'))
sys.exit(1 if bad else 0)
