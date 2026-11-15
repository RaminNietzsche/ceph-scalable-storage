#!/usr/bin/env python3
"""Check the chapter-opening TL;DR boxes («حوصله ندارم»).

Every chapter in both editions must open (right after its front matter) with a
``::: {.tldr}`` div of 3 to 5 bullets; fa and en must have the same number of
bullets and the same number of code spans in each bullet.

Usage: tools/check_tldr.py
"""
from __future__ import annotations

import glob
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
errors: list[str] = []


def tldr(path):
    s = open(path, encoding='utf-8').read()
    m = re.match(r'---\n.*?\n---\n\s*::: \{\.tldr\}\n\n(.*?)\n\n:::\s*\n', s, re.S)
    if not m:
        errors.append(f'{os.path.relpath(path, ROOT)}: no ::: {{.tldr}} block right after the front matter')
        return None
    lines = m.group(1).split('\n')
    bad = [x for x in lines if not x.startswith('- ')]
    if bad:
        errors.append(f'{os.path.relpath(path, ROOT)}: TL;DR lines must be "- " bullets: {bad[0][:60]!r}')
    if not 3 <= len(lines) <= 5:
        errors.append(f'{os.path.relpath(path, ROOT)}: TL;DR has {len(lines)} bullets (3 to 5 expected)')
    if s.count('{.tldr}') != 1:
        errors.append(f'{os.path.relpath(path, ROOT)}: more than one TL;DR block')
    return lines


n = 0
for fa in sorted(glob.glob(os.path.join(ROOT, 'content', 'fa', 'chapters', '[0-9][0-9]-*.md'))):
    en = os.path.join(ROOT, 'content', 'en', 'chapters', os.path.basename(fa))
    a, b = tldr(fa), (tldr(en) if os.path.exists(en) else None)
    n += 1
    if a and b:
        if len(a) != len(b):
            errors.append(f'{os.path.basename(fa)}: fa has {len(a)} TL;DR bullets, en has {len(b)}')
        elif [x.count('`') for x in a] != [x.count('`') for x in b]:
            errors.append(f'{os.path.basename(fa)}: fa and en TL;DR bullets have different code spans')
for e in errors:
    print('tldr:', e)
print(f'tldr: {n} chapters x 2 editions, {len(errors)} problems')
sys.exit(1 if errors else 0)
