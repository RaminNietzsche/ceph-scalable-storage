#!/usr/bin/env python3
"""Keep content/<lang>/ structurally in sync with the Persian source.

For every file under content/fa/{chapters,front,appendices,answers}:
* if the target-language file is missing, create it as a copy of the Persian
  file with ``translation: pending`` (and ``lang: <lang>``) in its front matter;
* if the target file exists and is still ``translation: pending``, refresh its
  body from the Persian source (the front-matter title is kept).
Translated files (no ``translation: pending``) are never touched.

Usage: tools/sync_translations.py [--lang en] [--dry-run]
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib.mdlower import split_front_matter  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--lang', default='en')
ap.add_argument('--dry-run', action='store_true')
a = ap.parse_args()
SRC = os.path.join(ROOT, 'content', 'fa')
DST = os.path.join(ROOT, 'content', a.lang)
made = refreshed = 0
for sub in ('chapters', 'front', 'appendices', 'answers'):
    for f in sorted(glob.glob(os.path.join(SRC, sub, '*.md'))):
        rel = os.path.relpath(f, SRC)
        t = os.path.join(DST, rel)
        src = open(f, encoding='utf-8').read()
        if sub == 'answers':
            fm_s, body = {}, src.split('\n')
            has_fm = False
        else:
            fm_text, body = split_front_matter(src)
            fm_s = yaml.safe_load(fm_text) or {}
            has_fm = True
        if os.path.exists(t):
            old = open(t, encoding='utf-8').read()
            if sub == 'answers':
                if not old.startswith('<!-- translation: pending -->'):
                    continue
                fm_t = {}
            else:
                fm_t = yaml.safe_load(split_front_matter(old)[0]) or {}
                if fm_t.get('translation') != 'pending':
                    continue
            action = 'refresh'
        else:
            fm_t = {}
            action = 'create'
        if sub == 'answers':
            out = '<!-- translation: pending -->\n' + '\n'.join(body)
        else:
            fm = dict(fm_s)
            fm.update({k: v for k, v in fm_t.items() if k in ('title',)})
            fm['lang'] = a.lang
            fm['translation'] = 'pending'
            out = '---\n' + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, width=1000) + '---\n' + '\n'.join(body)
        if a.dry_run:
            print(action, rel)
        else:
            os.makedirs(os.path.dirname(t), exist_ok=True)
            if action == 'create' or out != old:
                open(t, 'w', encoding='utf-8').write(out)
        made += action == 'create'
        refreshed += action == 'refresh'
print(f'sync_translations: created {made}, refreshed {refreshed} pending file(s) for {a.lang}')
