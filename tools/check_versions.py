#!/usr/bin/env python3
"""Check the Ceph release labels and the release-changes data.

* every ``{since=...}`` on a code fence names a known release (or main / none);
* fa and en label the same code blocks with the same release, block by block;
* references/ceph-release-changes.yaml is well formed: known releases with a
  version, date and notes URL; every change has an area, existing chapters, a
  status (confirmed | review) and both an en and a fa text;
* every release used as a label (other than the baseline and main) has a
  section in the changes appendix, so the badge links resolve.

Usage: tools/check_versions.py [-v]   (-v lists the blocks labelled newer than the baseline)
"""
from __future__ import annotations

import glob
import os
import re
import sys

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib import cephver  # noqa: E402

errors: list[str] = []
verbose = '-v' in sys.argv[1:]


def labels(path):
    lines = open(path, encoding='utf-8').read().split('\n')
    out = []
    for i, lang, attrs, body in cephver.blocks(lines):
        s = attrs.get('since')
        if s and s not in cephver.VALID:
            errors.append(f'{os.path.relpath(path, ROOT)}:{i + 1}: unknown since={s!r} (valid: {", ".join(cephver.VALID)})')
        out.append((i + 1, cephver.since_of(lang, attrs, body), body))
    return out


used = set()
n_badged = 0
for fa_path in sorted(glob.glob(os.path.join(ROOT, 'content', 'fa', '**', '*.md'), recursive=True)):
    rel = os.path.relpath(fa_path, os.path.join(ROOT, 'content', 'fa'))
    en_path = os.path.join(ROOT, 'content', 'en', rel)
    fa_l = labels(fa_path)
    if not os.path.exists(en_path):
        continue
    en_l = labels(en_path)
    if len(fa_l) != len(en_l):
        continue  # block counts are check_parity's job
    for k, ((lf, sf, body), (le, se, _)) in enumerate(zip(fa_l, en_l)):
        if sf != se:
            errors.append(f'{rel}: code block {k + 1} (fa line {lf}, en line {le}): fa label {sf} != en label {se}')
        if sf:
            n_badged += 1
            used.add(sf)
            if verbose and sf != cephver.BASELINE:
                first = next((b for b in body if cephver.CMD.match(b)), body[0] if body else '')
                print(f'{cephver.label(sf):10} {rel}:{lf}  {first.strip()}')

RC = yaml.safe_load(open(os.path.join(ROOT, 'references', 'ceph-release-changes.yaml'), encoding='utf-8'))
chapters = {int(re.match(r'(\d+)-', os.path.basename(p)).group(1))
            for p in glob.glob(os.path.join(ROOT, 'content', 'en', 'chapters', '[0-9][0-9]-*.md'))}
for rk, ri in (RC.get('releases') or {}).items():
    if rk not in cephver.REL:
        errors.append(f'ceph-release-changes.yaml: unknown release {rk!r}')
    for f in ('version', 'date', 'notes'):
        if not ri.get(f):
            errors.append(f'ceph-release-changes.yaml: release {rk} has no {f}')
    if not str(ri.get('version', '')).startswith(str(cephver.REL.get(rk, (0,))[0]) + '.'):
        errors.append(f'ceph-release-changes.yaml: release {rk} version {ri.get("version")} does not match its major number')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(ri.get('date', ''))):
        errors.append(f'ceph-release-changes.yaml: release {rk} date {ri.get("date")!r} is not YYYY-MM-DD')
    if not str(ri.get('notes', '')).startswith('https://'):
        errors.append(f'ceph-release-changes.yaml: release {rk} notes is not an https URL')
review = 0
for k, c in enumerate(RC.get('changes') or [], 1):
    where = f'ceph-release-changes.yaml: change {k}'
    if c.get('rel') not in (RC.get('releases') or {}):
        errors.append(f'{where}: rel {c.get("rel")!r} has no entry under releases')
    if c.get('status') not in ('confirmed', 'review'):
        errors.append(f'{where}: status must be confirmed or review, not {c.get("status")!r}')
    review += c.get('status') == 'review'
    if not c.get('area'):
        errors.append(f'{where}: no area')
    if not c.get('ch') or any(n not in chapters for n in c['ch']):
        errors.append(f'{where}: chapters {c.get("ch")} are missing or do not exist')
    for lang in ('en', 'fa'):
        if not (c.get(lang) or '').strip():
            errors.append(f'{where}: no {lang} text')
    if c.get('en', '').count('`') != c.get('fa', '').count('`'):
        errors.append(f'{where}: en and fa have a different number of code spans')
for s in sorted(used - {cephver.BASELINE, 'main'}):
    if s not in (RC.get('releases') or {}):
        errors.append(f'label {s} is used on code blocks but the changes appendix has no {s} section (badge links to changes.html#rel-{s})')

for e in errors:
    print('versions:', e)
print(f'versions: {n_badged} labelled blocks per edition, labels used: {", ".join(sorted(used))}; '
      f'{len(RC.get("changes") or [])} changes ({review} for review); {len(errors)} problems')
sys.exit(1 if errors else 0)
