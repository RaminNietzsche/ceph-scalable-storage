#!/usr/bin/env python3
"""Check internal references and assets for one or both editions.

* every image referenced in a chapter exists (language variant or shared);
* figure, section and ALGO ids are unique and follow the chapter numbering;
* every figure file in figures/chNN/ is referenced by the chapter (warning);
* the number of answers matches the number of review questions;
* glossary terms are unique; references.json URLs are unique.

Usage: tools/check_refs.py [--lang fa|en|all]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib.mdlower import heading_ids, split_front_matter, lower  # noqa: E402
from booklib.structure import skeleton  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--lang', default='all')
a = ap.parse_args()
langs = ['fa', 'en'] if a.lang == 'all' else [a.lang]
err, warn = [], []
for lang in langs:
    C = os.path.join(ROOT, 'content', lang)
    UI = yaml.safe_load(open(os.path.join(C, 'ui.yaml'), encoding='utf-8'))
    seen = {}
    for path in sorted(glob.glob(os.path.join(C, 'chapters', '*.md'))):
        rel = os.path.relpath(path, ROOT)
        sk = skeleton(path)
        n = int(sk['fm'].get('chapter', 0))
        if not re.match(rf'^{n:02d}-[a-z0-9-]+\.md$', os.path.basename(path)):
            err.append(f'{rel}: file name must be NN-kebab-slug.md matching chapter {n}')
        for ident in sk['sections'] + sk['figures'] + sk['algos']:
            if ident in seen:
                err.append(f'{rel}: duplicate id {ident} (also in {seen[ident]})')
            seen[ident] = rel
        for k, f in enumerate(sk['figures']):
            if not f.startswith(f'fig-{n:02d}-'):
                err.append(f'{rel}: figure id {f} does not match chapter')
        for k, al in enumerate(sk['algos']):
            if al != f'alg-{n:02d}-{k + 1}':
                err.append(f'{rel}: ALGO id {al} out of sequence (expected alg-{n:02d}-{k + 1})')
        _, lines = split_front_matter(open(path, encoding='utf-8').read())
        stripped = [re.sub(r'\s+\{#[\w:.-]+\}\s*$', '', x) for x in lines]
        expect = [h for _, _, h in heading_ids(stripped, n)]
        if expect != sk['sections']:
            err.append(f'{rel}: section ids not sequential (run tools/renumber_sections.py)')
        for img in sk['images']:
            full = os.path.join(ROOT, img)
            stem, ext = os.path.splitext(full)
            if not (os.path.exists(full) or os.path.exists(f'{stem}.{lang}{ext}')):
                err.append(f'{rel}: missing image {img}')
        if lang == 'fa':
            used = {os.path.basename(i) for i in sk['images']}
            for f in glob.glob(os.path.join(ROOT, 'figures', f'ch{n:02d}', '*.png')):
                b = os.path.basename(f)
                base = re.sub(r'\.(fa|en)\.png$', '.png', b)
                if base not in used:
                    warn.append(f'figures/ch{n:02d}/{b}: not referenced by the chapter')
        if sk['fm'].get('translation') != 'pending':
            low = lower(lines)
            q = 0
            mode = False
            inc = False
            for x in low:
                if x.startswith('```'):
                    inc = not inc
                if not inc and re.match(r'^#{1,2} ', x):
                    mode = x.split(' ', 1)[1].strip().startswith(UI['review_questions'])
                elif mode and re.match(r'^\d+\. ', x):
                    q += 1
            ap_ = os.path.join(C, 'answers', f'{n:02d}.md')
            na = sum(1 for x in open(ap_, encoding='utf-8') if x.strip() and not x.startswith('<!--')) if os.path.exists(ap_) else 0
            if q != na:
                err.append(f'{rel}: {q} review questions but {na} answers')
G = yaml.safe_load(open(os.path.join(ROOT, 'glossary', 'glossary.yaml'), encoding='utf-8'))
terms = [g['term'].lower() for g in G]
for t in sorted({t for t in terms if terms.count(t) > 1}):
    err.append(f'glossary: duplicate term {t}')
R = json.load(open(os.path.join(ROOT, 'references', 'references.json'), encoding='utf-8'))
urls = [r['URL'] for r in R]
for u in sorted({u for u in urls if urls.count(u) > 1}):
    err.append(f'references.json: duplicate URL {u}')
print(f'check-refs: {len(err)} error(s), {len(warn)} warning(s)')
for e in err:
    print('  ERROR', e)
for w in warn[:50]:
    print('  warn ', w)
sys.exit(1 if err else 0)
