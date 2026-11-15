#!/usr/bin/env python3
"""Warn when a pull request changes content/fa without the matching content/en file.

Exits 0 after printing GitHub workflow warning annotations so the check is
visible on the PR but does not block the merge by itself. Full structural
parity remains `make check-parity`.
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def git(*args: str) -> str:
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def base_sha() -> str:
    env = os.environ.get('PR_BASE_SHA') or os.environ.get('GITHUB_BASE_SHA') or ''
    if env:
        return env
    for cand in ('origin/main', 'main'):
        try:
            git('rev-parse', '--verify', cand)
            return git('merge-base', cand, 'HEAD')
        except subprocess.CalledProcessError:
            continue
    return 'HEAD~1'


def main() -> int:
    base = base_sha()
    try:
        names = [n for n in git('diff', '--name-only', '--diff-filter=ACMR', f'{base}...HEAD').splitlines() if n]
    except subprocess.CalledProcessError as e:
        print(f'::warning::could not diff against {base}: {e}')
        return 0
    fa = [n for n in names if n.startswith('content/fa/')]
    if not fa:
        print(f'check-translation-pr: no content/fa changes versus {base}')
        return 0
    warned = 0
    for rel in fa:
        en = 'content/en/' + rel[len('content/fa/'):]
        if en in names:
            continue
        en_path = os.path.join(ROOT, en)
        if os.path.exists(en_path):
            print(f'::warning file={rel}::Persian content changed without a matching change to {en}')
        else:
            print(f'::warning file={rel}::Persian content changed and {en} does not exist (translation missing)')
        warned += 1
    print(f'check-translation-pr: {len(fa)} fa file(s) changed, {warned} without a matching en path (base {base})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
