#!/usr/bin/env python3
"""Check the chapter-opening TL;DR boxes («حوصله ندارم»).

Every chapter in both editions must open (right after its front matter) with a
``::: {.tldr}`` div containing:
  * 3 to 5 ``- `` bullets (fa and en have the same bullet count and code spans);
  * 0 or 1 fenced Ceph CLI command block (fa and en agree on presence & ``since``);
  * 1 figure thumbnail link ``[![caption](figures/chNN/name.png)](#fig-NN-name)``
    pointing to an existing figure of that same chapter (fa and en agree on figure).

Usage: tools/check_tldr.py
"""
from __future__ import annotations

import glob
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib import cephver  # noqa: E402
from booklib.structure import skeleton  # noqa: E402

errors: list[str] = []
FIG_LINK = re.compile(r'^\[!\[([^\]]+)\]\((figures/ch\d+/[^)\s]+)\)\]\(#(fig-\d+-[^)\s]+)\)$')


def tldr(path):
    rel = os.path.relpath(path, ROOT)
    s = open(path, encoding='utf-8').read()
    m = re.match(r'---\n.*?\n---\n\s*::: \{\.tldr\}\n\n(.*?)\n\n:::\s*\n', s, re.S)
    if not m:
        errors.append(f'{rel}: no ::: {{.tldr}} block right after the front matter')
        return None
    if s.count('{.tldr}') != 1:
        errors.append(f'{rel}: more than one TL;DR block')

    lines = m.group(1).split('\n')
    bullets = []
    cmds = []
    figs = []
    i = 0
    # 1) leading bullets
    while i < len(lines):
        ln = lines[i]
        if ln == '':
            i += 1
            continue
        if ln.startswith('- ') and not cmds and not figs:
            bullets.append(ln)
            i += 1
            continue
        if ln.startswith('```'):
            f = cephver.parse_fence(ln)
            lang, attrs = f if f else (ln[3:].strip(), {})
            i += 1
            body = []
            while i < len(lines) and not lines[i].startswith('```'):
                body.append(lines[i])
                i += 1
            if i >= len(lines):
                errors.append(f'{rel}: unclosed code block in TL;DR')
                break
            i += 1
            if not cephver.is_ceph_command(lang, body):
                errors.append(f'{rel}: TL;DR code block must run a real Ceph CLI tool')
            cmds.append((cephver.since_of(lang, attrs, body), '\n'.join(body)))
            continue
        fm = FIG_LINK.match(ln)
        if fm:
            figs.append((fm.group(3), fm.group(2), fm.group(1)))
            i += 1
            continue
        errors.append(f'{rel}: unexpected line inside TL;DR: {ln[:70]!r}')
        i += 1

    if not 3 <= len(bullets) <= 5:
        errors.append(f'{rel}: TL;DR has {len(bullets)} bullets (3 to 5 expected)')
    if len(cmds) > 1:
        errors.append(f'{rel}: TL;DR has {len(cmds)} command blocks (at most 1 expected)')
    if len(figs) != 1:
        errors.append(f'{rel}: TL;DR has {len(figs)} figure thumbnail links (expected 1)')
    else:
        fid, fpath, _ = figs[0]
        sk = skeleton(path)
        chap_figs = dict(zip(sk['figures'], sk['images']))
        if fid not in chap_figs:
            errors.append(f'{rel}: TL;DR figure #{fid} does not exist in this chapter')
        elif chap_figs[fid] != fpath:
            errors.append(f'{rel}: TL;DR figure path {fpath} != {chap_figs[fid]} for #{fid}')
    return bullets, cmds, figs


n = 0
for fa in sorted(glob.glob(os.path.join(ROOT, 'content', 'fa', 'chapters', '[0-9][0-9]-*.md'))):
    en = os.path.join(ROOT, 'content', 'en', 'chapters', os.path.basename(fa))
    a, b = tldr(fa), (tldr(en) if os.path.exists(en) else None)
    n += 1
    if a and b:
        ba, ca, fa_figs = a
        bb, cb, en_figs = b
        if len(ba) != len(bb):
            errors.append(f'{os.path.basename(fa)}: fa has {len(ba)} TL;DR bullets, en has {len(bb)}')
        elif [x.count('`') for x in ba] != [x.count('`') for x in bb]:
            errors.append(f'{os.path.basename(fa)}: fa and en TL;DR bullets have different code spans')
        if len(ca) != len(cb):
            errors.append(f'{os.path.basename(fa)}: fa has {len(ca)} TL;DR command(s), en has {len(cb)}')
        elif ca and cb and ca[0][0] != cb[0][0]:
            errors.append(f'{os.path.basename(fa)}: fa and en TL;DR command release labels differ ({ca[0][0]} vs {cb[0][0]})')
        if len(fa_figs) == 1 and len(en_figs) == 1:
            if fa_figs[0][:2] != en_figs[0][:2]:
                errors.append(f'{os.path.basename(fa)}: fa TL;DR figure {fa_figs[0][:2]} != en {en_figs[0][:2]}')

for e in errors:
    print('tldr:', e)
print(f'tldr: {n} chapters x 2 editions, {len(errors)} problems')
sys.exit(1 if errors else 0)
