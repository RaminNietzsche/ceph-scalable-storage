#!/usr/bin/env python3
"""Spelling and orthography checks for the prose (outside code blocks).

Persian (fa):
  * Arabic code points that should be Persian: ي (U+064A) -> ی, ك (U+0643) -> ک
  * the "می " / "نمی " prefix written with a plain space instead of ZWNJ
  * doubled spaces, space before Persian punctuation (، ؛ ؟), trailing spaces
Both: a bare ^ exponent outside code and $...$ math (write $10^{-14}$, or a Unicode
  superscript in titles, headings, captions and algorithm attributes), an unbalanced $,
  Persian digits or RLM/LRM marks inside math.
English (en): runs codespell (if installed) on translated files, plus the
  whitespace checks. Pending translations are skipped for English.

Usage: tools/lint_prose.py --lang fa|en|all [--max N]
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ap = argparse.ArgumentParser()
ap.add_argument('--lang', default='all')
ap.add_argument('--max', type=int, default=40)
a = ap.parse_args()
langs = ['fa', 'en'] if a.lang == 'all' else [a.lang]
RULES_FA = [
    (re.compile('[\u064A\u0643]'), 'Arabic ي/ك instead of Persian ی/ک'),
    (re.compile(r'(?<![\w\u200c])(ن?می) (?=[\u0600-\u06FF]{2,})'), '"می"/"نمی" prefix should be joined with ZWNJ (U+200C)'),
    (re.compile(r' [،؛؟]'), 'space before Persian punctuation'),
]
MATH = re.compile(r'\$(?=\S)[^$\n]+?(?<=\S)\$(?!\d)')
RULES_ALL = [
    (re.compile(r'\w\)?\^[\w({-]'), 'bare ^ exponent outside code/math: use $...$ (or a Unicode superscript in plain-text contexts)'),
    (re.compile(r'\S  +\S'), 'double space'),
    (re.compile(r'[ \t]+$'), 'trailing whitespace'),
]
issues = []
for lang in langs:
    files = sorted(glob.glob(os.path.join(ROOT, 'content', lang, '**', '*.md'), recursive=True))
    todo_en = []
    for f in files:
        text = open(f, encoding='utf-8').read()
        if lang == 'en' and ('translation: pending' in text.split('\n---', 2)[0][:400] or text.startswith('<!-- translation: pending -->')):
            continue
        if lang == 'en':
            todo_en.append(f)
        inc = False
        for ln, line in enumerate(text.split('\n'), 1):
            if line.startswith('```'):
                inc = not inc
                continue
            if inc:
                continue
            prose = re.sub(r'`[^`]*`', 'CODE', line)
            for m in MATH.finditer(prose):
                if re.search('[\u06F0-\u06F9\u0660-\u0669\u200e\u200f]', m.group(0)):
                    issues.append(f'{os.path.relpath(f, ROOT)}:{ln}: Persian digits or bidi marks inside math {m.group(0)}')
            prose = MATH.sub('MATH', prose)
            if prose.count('$') % 2:
                issues.append(f'{os.path.relpath(f, ROOT)}:{ln}: unbalanced $ (inline math must be $...$ with no inner space at the ends)')
            rules = RULES_ALL + (RULES_FA if lang == 'fa' else [])
            for rx, msg in rules:
                if msg == 'double space' and prose.startswith('|'):
                    continue  # aligned/empty table cells
                if rx.search(prose):
                    issues.append(f'{os.path.relpath(f, ROOT)}:{ln}: {msg}')
    if lang == 'en' and todo_en:
        cs = shutil.which('codespell') or os.path.expanduser('~/.local/bin/codespell')
        if os.path.exists(cs):
            r = subprocess.run([cs, '--ignore-words', os.path.join(ROOT, '.codespell-ignore'), *todo_en], capture_output=True, text=True)
            issues += [x for x in r.stdout.splitlines() if x.strip()]
        else:
            print('lint-prose: codespell not installed; English spelling not checked')
print(f'lint-prose: {len(issues)} issue(s)')
for i in issues[:a.max]:
    print('  ', i.replace(ROOT + '/', ''))
if len(issues) > a.max:
    print(f'   ... and {len(issues) - a.max} more')
sys.exit(1 if issues else 0)
