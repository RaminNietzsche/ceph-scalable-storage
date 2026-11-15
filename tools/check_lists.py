#!/usr/bin/env python3
"""Content checks of the built web book that link checks cannot see.

* No soft hyphen (U+00AD) in any page: copied text must not contain them.
* Math: no raw $...$ TeX or build placeholders left in prose; every page with
  KaTeX output links the bundled katex.min.css; formulas are LTR-isolated.

Usage: tools/check_lists.py [--site build/site]
"""
from __future__ import annotations

import argparse
import os
import re
import sys

from bs4 import BeautifulSoup

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

ap = argparse.ArgumentParser()
ap.add_argument('--site', default=os.path.join(ROOT, 'build', 'site'))
SITE = os.path.abspath(ap.parse_args().site)
problems = []
summary = []
cache = {}


def page(lang, slug):
    k = (lang, slug)
    if k not in cache:
        p = os.path.join(SITE, lang, slug + '.html')
        cache[k] = BeautifulSoup(open(p, encoding='utf-8').read(), 'html.parser') if os.path.exists(p) else None
    return cache[k]


def norm(s):
    return re.sub(r'\s+', ' ', s.replace('\u200f', '').replace('\u200e', '')).strip()


def text(node):
    node = BeautifulSoup(str(node), 'html.parser')
    for m in node.select('.math[data-plain]'):
        m.replace_with(m['data-plain'])
    return norm(node.get_text(' '))


# ---- whole site: soft hyphens, math leftovers
n_pages = 0
for lang in ('fa', 'en'):
    for fn in sorted(os.listdir(os.path.join(SITE, lang))):
        if not fn.endswith('.html'):
            continue
        n_pages += 1
        raw = open(os.path.join(SITE, lang, fn), encoding='utf-8').read()
        if '\u00ad' in raw or '&shy;' in raw:
            problems.append(f'{lang}/{fn}: contains soft hyphens (U+00AD)')
        if '\ue000' in raw or '\ue001' in raw:
            problems.append(f'{lang}/{fn}: unreplaced math placeholder')
        if 'class="katex"' in raw and 'katex/katex.min.css' not in raw:
            problems.append(f'{lang}/{fn}: KaTeX output without the katex stylesheet')
        soup = BeautifulSoup(raw, 'html.parser')
        main = soup.find('main') or soup
        for el in main.select('.math'):
            if el.get('dir') != 'ltr':
                problems.append(f'{lang}/{fn}: formula without dir=ltr')
        for x in main.select('pre, code, script, .katex, .math, .term'):
            x.decompose()
        t = main.get_text(' ')
        for m in re.finditer(r'\$(?=\S)[^$\n]+?(?<=\S)\$(?!\d)', t):
            problems.append(f'{lang}/{fn}: raw TeX in text: {m.group(0)[:40]}')
        for m in re.finditer(r'\w\)?\^[\w({-]', t):
            problems.append(f'{lang}/{fn}: bare ^ exponent in text: …{t[max(0, m.start() - 15):m.end() + 10]}…')
            break
summary.append(f'{n_pages} pages')

for p in problems[:60]:
    print('check_lists:', p)
if len(problems) > 60:
    print(f'check_lists: ... and {len(problems) - 60} more')
print(f'check_lists: {", ".join(summary)}; {len(problems)} problems')
sys.exit(1 if problems else 0)
