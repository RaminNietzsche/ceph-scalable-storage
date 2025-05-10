#!/usr/bin/env python3
"""Check that the Persian and English editions have the same structure.

Compares, file by file: the chapter set, section anchors, figure ids, ALGO ids,
number of tables, code blocks and callouts, and the number of answers.
Pending translations are listed; with --strict they count as failures.

Usage: tools/check_parity.py [--strict]
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib.structure import skeleton  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--strict', action='store_true', help='treat pending translations as errors')
a = ap.parse_args()
FA = os.path.join(ROOT, 'content', 'fa')
EN = os.path.join(ROOT, 'content', 'en')
errors = []
pending = []


def rels(base, sub):
    return sorted(os.path.relpath(f, base) for f in glob.glob(os.path.join(base, sub, '*.md')))


for sub in ('chapters', 'front', 'appendices', 'answers'):
    f1, f2 = rels(FA, sub), rels(EN, sub)
    for x in sorted(set(f1) ^ set(f2)):
        errors.append(f'{x}: present in only one language')
for rel in rels(FA, 'chapters') + rels(FA, 'front') + rels(FA, 'appendices'):
    p2 = os.path.join(EN, rel)
    if not os.path.exists(p2):
        continue
    s1, s2 = skeleton(os.path.join(FA, rel)), skeleton(p2)
    if s2['fm'].get('translation') == 'pending':
        pending.append(rel)
    for key in ('sections', 'figures', 'algos', 'tables', 'code_blocks', 'callouts'):
        if s1[key] != s2[key]:
            if isinstance(s1[key], list):
                miss = [x for x in s1[key] if x not in s2[key]]
                extra = [x for x in s2[key] if x not in s1[key]]
                detail = f'missing {miss[:5]} extra {extra[:5]}' if (miss or extra) else 'order differs'
            else:
                detail = f'fa={s1[key]} en={s2[key]}'
            errors.append(f'{rel}: {key} differ ({detail})')
    for k in ('chapter', 'id', 'part'):
        if s1['fm'].get(k) != s2['fm'].get(k):
            errors.append(f'{rel}: front matter {k} differs')
for rel in rels(FA, 'answers'):
    p2 = os.path.join(EN, rel)
    if not os.path.exists(p2):
        continue
    n1 = sum(1 for x in open(os.path.join(FA, rel), encoding='utf-8') if x.strip() and not x.startswith('<!--'))
    t2 = open(p2, encoding='utf-8').read()
    n2 = sum(1 for x in t2.split('\n') if x.strip() and not x.startswith('<!--'))
    if t2.startswith('<!-- translation: pending -->'):
        pending.append(rel)
    if n1 != n2:
        errors.append(f'{rel}: answer count fa={n1} en={n2}')
chap_pending = [p for p in pending if p.startswith('chapters/')]
print(f'check-parity: {len(errors)} error(s); {len(chap_pending)} chapter(s) and {len(pending) - len(chap_pending)} other file(s) pending translation')
for e in errors:
    print('  ERROR', e)
if pending:
    print('  pending:', ', '.join(sorted(pending)))
sys.exit(1 if errors or (a.strict and pending) else 0)
