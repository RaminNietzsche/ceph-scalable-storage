#!/usr/bin/env python3
"""Generate per-language Mermaid variants from the single Persian source.

Labels live in figures/i18n/<lang>.yaml:

    _common:              # applies to every figure
      "و": "and"
    ch01/f01_stack:       # per figure (path under figures/, without .mmd)
      "مصرف‌کنندگان": "Consumers"

Every maximal run of Persian words in a .mmd file is a translatable string.
Keys that are not a single Persian run (Latin text, <br/>, punctuation) are whole-phrase
overrides (applied first), for
labels whose English word order differs, e.g. "keyring مدیر": "admin keyring".
A variant <name>.<lang>.mmd is written only when *all* runs are translated;
otherwise the build falls back to the Persian figure and the gap is reported.

Usage:
  tools/translate_figures.py --lang en            # write variants, report gaps
  tools/translate_figures.py --lang en --extract  # add missing keys (null) to the yaml
  tools/translate_figures.py --lang en --extract ch01 ch02
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
FIG = os.path.join(ROOT, 'figures')
RUN = re.compile(r'[\u0600-\u06FF](?:[\u0600-\u06FF\u200c\u060c\u061b\u061f\u06F0-\u06F9«» ]*[\u0600-\u06FF\u06F0-\u06F9»])?')
ap = argparse.ArgumentParser()
ap.add_argument('--lang', default='en')
ap.add_argument('--extract', action='store_true')
ap.add_argument('chapters', nargs='*')
a = ap.parse_args()
yf = os.path.join(FIG, 'i18n', f'{a.lang}.yaml')
tr = (yaml.safe_load(open(yf, encoding='utf-8')) if os.path.exists(yf) else None) or {}
common = tr.get('_common') or {}
DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٬٫،', '0123456789,.,')
AUTO = re.compile(r'^[\u06F0-\u06F9\u060c\u066b\u066c ]+$')


def lookup(local, r):
    if local.get(r) or common.get(r):
        return local.get(r) or common.get(r)
    if AUTO.match(r):
        return r.translate(DIGITS)
    return None

dirs = [os.path.join(FIG, c) for c in a.chapters] or sorted(glob.glob(os.path.join(FIG, 'ch[0-9][0-9]')))
written = partial = untouched = 0
gaps = {}
for d in dirs:
    for src in sorted(glob.glob(os.path.join(d, '*.mmd'))):
        base = os.path.basename(src)
        if base.count('.') > 1:
            continue
        key = os.path.relpath(src, FIG)[:-4]
        text = orig = open(src, encoding='utf-8').read()
        local = tr.get(key) or {}
        # phrase keys (containing Latin text) are whole-label overrides applied first,
        # for labels whose English word order differs from the Persian
        for k in sorted((k for k in local if not RUN.fullmatch(k) and local[k]), key=len, reverse=True):
            text = text.replace(k, local[k])
        runs = list(dict.fromkeys(m.group(0).strip() for m in RUN.finditer(text)))
        if not runs and text == orig:
            continue
        missing = [r for r in runs if lookup(local, r) is None]
        if a.extract:
            if missing:
                tr.setdefault(key, {})
                tr[key] = {**(tr[key] or {}), **{r: None for r in missing}}
            continue
        out = src[:-4] + f'.{a.lang}.mmd'
        if missing:
            gaps[key] = len(missing)
            partial += 1 if len(missing) < len(runs) else 0
            untouched += 1 if len(missing) == len(runs) else 0
            continue
        res = RUN.sub(lambda m: m.group(0).replace(m.group(0).strip(), lookup(local, m.group(0).strip())), text)
        if not os.path.exists(out) or open(out, encoding='utf-8').read() != res:
            open(out, 'w', encoding='utf-8').write(res)
            written += 1
if a.extract:
    with open(yf, 'w', encoding='utf-8') as f:
        f.write(f'# Mermaid label strings for the {a.lang} edition; see tools/translate_figures.py\n')
        yaml.safe_dump(tr, f, allow_unicode=True, sort_keys=False, width=200)
    print('extract: wrote', os.path.relpath(yf, ROOT))
    sys.exit(0)
print(f'translate_figures[{a.lang}]: {written} variants updated; '
      f'{len(gaps)} figures still Persian-only ({untouched} untranslated, {partial} partial)')
