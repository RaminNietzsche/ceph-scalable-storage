#!/usr/bin/env python3
"""Validate references/cheatsheet.yaml (schema, categories, anchors, prose lint, commands)."""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib import cephver  # noqa: E402
from check_ceph_commands import TOOLS, simple_commands  # noqa: E402

EXPECTED_CATS = (
    'status', 'mon_mgr', 'osd', 'pools_crush', 'balancer', 'bluestore',
    'rbd', 'cephfs', 'rgw', 'auth', 'orch', 'upgrade', 'debug', 'perf',
)
VALID_APPS = {'appA', 'appB', 'appC', 'appD', 'appF', 'appG', 'appH', 'appI', 'appJ', 'appK', 'appL', 'appM'}

RULES_FA = [
    (re.compile('[\u064A\u0643]'), 'Arabic ي/ك instead of Persian ی/ک'),
    (re.compile(r'(?<![\w\u200c])(ن?می) (?=[\u0600-\u06FF]{2,})'), '"می"/"نمی" prefix should use ZWNJ'),
    (re.compile(r' [،؛؟]'), 'space before Persian punctuation'),
]
RULES_ALL = [
    (re.compile(r'\w\)?\^[\w({-]'), 'bare ^ exponent outside math'),
    (re.compile(r'\S  +\S'), 'double space'),
    (re.compile(r'[ \t]+$'), 'trailing whitespace'),
]
ANCHOR_RX = re.compile(r'\{#([A-Za-z0-9_:-]+)\}')


def collect_anchors(lang: str) -> set[str]:
    anchors = set(VALID_APPS)
    for p in glob.glob(os.path.join(ROOT, 'content', lang, '**', '*.md'), recursive=True):
        txt = open(p, encoding='utf-8').read()
        for m in ANCHOR_RX.finditer(txt):
            anchors.add(m.group(1))
    return anchors


def lint_text(text: str, lang: str, where: str, errs: list[str]) -> None:
    if not isinstance(text, str) or not text.strip():
        errs.append(f'{where}: empty {lang} text')
        return
    if text.count('$') % 2:
        errs.append(f'{where}: unbalanced $ in {lang}')
    rules = RULES_ALL + (RULES_FA if lang == 'fa' else [])
    for rx, msg in rules:
        if rx.search(text):
            errs.append(f'{where} ({lang}): {msg} -> {text!r}')


def main() -> int:
    path = os.path.join(ROOT, 'references', 'cheatsheet.yaml')
    if not os.path.exists(path):
        print('check-cheatsheet: references/cheatsheet.yaml missing', file=sys.stderr)
        return 1
    data = yaml.safe_load(open(path, encoding='utf-8')) or {}
    cats = data.get('categories')
    if not isinstance(cats, list):
        print('check-cheatsheet: top-level categories must be a list', file=sys.stderr)
        return 1

    errs: list[str] = []
    seen_cats: list[str] = []
    seen_cmds: set[str] = set()
    en_lines: list[str] = []
    anchors_fa = collect_anchors('fa')
    anchors_en = collect_anchors('en')
    total_cmds = 0

    for ci, cat in enumerate(cats):
        cid = cat.get('id')
        if not cid or not isinstance(cid, str):
            errs.append(f'category #{ci}: missing id')
            continue
        seen_cats.append(cid)
        lint_text(cat.get('fa', ''), 'fa', f'cat:{cid}', errs)
        lint_text(cat.get('en', ''), 'en', f'cat:{cid}', errs)
        en_lines.append(str(cat.get('en', '')))
        cmds = cat.get('commands') or []
        if len(cmds) < 6:
            errs.append(f'cat:{cid}: expected at least 6 commands, got {len(cmds)}')
        for ei, entry in enumerate(cmds):
            total_cmds += 1
            where = f'{cid}[{ei}]'
            cmd = entry.get('cmd', '')
            if not cmd or not isinstance(cmd, str) or cmd.strip() != cmd:
                errs.append(f'{where}: invalid or untrimmed cmd {cmd!r}')
                continue
            if cmd in seen_cmds:
                errs.append(f'{where}: duplicate cmd {cmd!r}')
            seen_cmds.add(cmd)
            inv = simple_commands(cmd, 'bash')
            if not inv or not any(a[0] in TOOLS for a in inv):
                errs.append(f'{where}: cmd does not invoke a recognized Ceph tool: {cmd!r}')
            lint_text(entry.get('fa', ''), 'fa', where, errs)
            lint_text(entry.get('en', ''), 'en', where, errs)
            en_lines.append(str(entry.get('en', '')))
            ref = entry.get('ref', '')
            if not ref or not isinstance(ref, str):
                errs.append(f'{where}: missing ref')
            else:
                if ref not in anchors_fa:
                    errs.append(f'{where}: ref #{ref} not found in content/fa')
                if ref not in anchors_en:
                    errs.append(f'{where}: ref #{ref} not found in content/en')
            since = entry.get('since')
            if since is not None:
                if since not in cephver.VALID or since == 'none':
                    errs.append(f'{where}: invalid since={since!r}')
            danger = entry.get('danger')
            if danger is not None and not isinstance(danger, bool):
                errs.append(f'{where}: danger must be bool, got {danger!r}')

    if tuple(seen_cats) != EXPECTED_CATS:
        errs.append(f'categories mismatch: got {seen_cats}, expected {list(EXPECTED_CATS)}')

    cs = shutil.which('codespell') or os.path.expanduser('~/.local/bin/codespell')
    if cs and os.path.exists(cs):
        with tempfile.NamedTemporaryFile('w', suffix='.txt', encoding='utf-8', delete=False) as tf:
            tf.write('\n'.join(en_lines) + '\n')
            tmp_p = tf.name
        try:
            r = subprocess.run([cs, '--ignore-words', os.path.join(ROOT, '.codespell-ignore'), tmp_p],
                               capture_output=True, text=True)
            for line in r.stdout.splitlines():
                if line.strip():
                    errs.append(f'codespell: {line.replace(tmp_p, "references/cheatsheet.yaml")}')
        finally:
            os.unlink(tmp_p)

    print(f'check-cheatsheet: {len(cats)} categories, {total_cmds} commands, {len(errs)} error(s)')
    for e in errs[:40]:
        print(' ', e)
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main())
