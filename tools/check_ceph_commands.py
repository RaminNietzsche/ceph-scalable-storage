#!/usr/bin/env python3
"""Best-effort comparison of Ceph CLI usage in the book with upstream docs.

Walks fenced code in content/fa and content/en for invocations of ceph, rbd,
rados, radosgw-admin, cephadm and ceph-volume. Fetches the latest Ceph man
pages (docs.ceph.com, current release) and reports subcommands or flags that
do not appear there. Report-only: exit 0 unless --strict.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from urllib.parse import urljoin

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
TOOLS = ('ceph', 'rbd', 'rados', 'radosgw-admin', 'cephadm', 'ceph-volume')
FENCE = re.compile((chr(96)*3).join(["^", r"[^\n]*\n(.*?)\n", ""]), re.M | re.S)
TOKEN = re.compile(r'(?:--[A-Za-z0-9][A-Za-z0-9_-]*|-[A-Za-z])')
INVOKE = re.compile(
    r'^(?P<pre>[ \t]*(?:\$ |# |sudo )?)(?P<tool>%s)(?P<rest>[^\n]*)$' % '|'.join(TOOLS),
    re.M,
)

ap = argparse.ArgumentParser()
ap.add_argument('--out', help='write Markdown report to this path (also printed)')
ap.add_argument('--strict', action='store_true', help='exit 1 when something looks unknown')
ap.add_argument('--docs-base', default='https://docs.ceph.com/en/latest/man/8/')
a = ap.parse_args()


def md_files():
    out = []
    for lang in ('fa', 'en'):
        base = os.path.join(ROOT, 'content', lang)
        for dirpath, _, files in os.walk(base):
            for fn in files:
                if fn.endswith('.md'):
                    out.append(os.path.join(dirpath, fn))
    return out


def split_argv(rest: str) -> list[str]:
    if not rest:
        return []
    rest = re.split(r'\s+[|&><]', rest, maxsplit=1)[0]
    return re.findall(r'(?:"[^"]*"|\S+)', rest)


def parse_invocation(tool: str, rest: str):
    argv = [x.strip('"') for x in split_argv(rest or '')]
    flags, words = [], []
    for t in argv:
        if t.startswith('-'):
            name = t.split('=', 1)[0]
            if name not in ('-', '--'):
                flags.append(name)
        elif t not in ('\\',) and not t.startswith('<'):
            words.append(t)
    return tuple(words[:4]), tuple(sorted(set(flags)))


def harvest():
    found = defaultdict(lambda: defaultdict(list))
    for path in md_files():
        rel = os.path.relpath(path, ROOT)
        text = open(path, encoding='utf-8').read()
        for body in FENCE.findall(text):
            for m in INVOKE.finditer(body):
                tool = m.group('tool')
                words, flags = parse_invocation(tool, m.group('rest'))
                found[tool][(words, flags)].append(rel)
    return found


def fetch(url: str):
    import requests
    r = requests.get(url, timeout=25, headers={'User-Agent': 'ceph-scalable-storage-book-ci'})
    r.raise_for_status()
    return r.text


def latest_label():
    try:
        html = fetch('https://docs.ceph.com/en/latest/releases/')
        m = re.search(r'Current[^*\n]*?([A-Z][a-z]+)\s+\(v?(\d+\.\d+\.\d+)\)', html)
        if m:
            return f'{m.group(1)} {m.group(2)}', 'https://docs.ceph.com/en/latest/releases/'
    except Exception as e:  # noqa: BLE001
        return f'(could not detect: {e})', 'https://docs.ceph.com/en/latest/releases/'
    return 'latest (docs.ceph.com/en/latest)', 'https://docs.ceph.com/en/latest/releases/'


def man_vocab(tool: str):
    url = urljoin(a.docs_base if a.docs_base.endswith('/') else a.docs_base + '/', f'{tool}/')
    try:
        from bs4 import BeautifulSoup
        html = fetch(url)
    except Exception as e:  # noqa: BLE001
        return set(), set(), url, str(e)
    soup = BeautifulSoup(html, 'lxml')
    text = soup.get_text('\n', strip=True)
    flags = set(TOKEN.findall(text))
    words = set()
    for m in re.finditer(rf'\b{re.escape(tool)}\s+([a-z][a-z0-9-]*)', text):
        words.add(m.group(1))
    for code in soup.select('code, span.pre, kbd, tt'):
        t = code.get_text().strip()
        if t.startswith('--') or re.fullmatch(r'-[A-Za-z]', t):
            flags.add(t.split('=', 1)[0])
        elif re.fullmatch(r'[a-z][a-z0-9-]{1,40}', t):
            words.add(t)
    return words, flags, url, ''


def main():
    found = harvest()
    release, rel_url = latest_label()
    lines = [
        f'Target docs: [{release}]({rel_url}), man base `{a.docs_base}`.',
        '',
        'This is a best-effort report. Man pages do not list every manager command or every',
        'positional argument; unknown items should be checked by hand, not treated as a CI failure.',
        '',
    ]
    problems = 0
    for tool in TOOLS:
        inv = found.get(tool) or {}
        docs_words, docs_flags, url, err = man_vocab(tool)
        lines.append(f'### `{tool}`')
        lines.append(f'Docs: <{url}>  ')
        if err:
            lines.append(f'Fetch failed: `{err}`')
            lines.append('')
            problems += 1
            continue
        lines.append(f'Indexed {len(docs_words)} subcommand-like tokens and {len(docs_flags)} flags from the man page.')
        n = sum(len(v) for v in inv.values())
        lines.append(f'Book: {n} invocation(s) in {len({f for fs in inv.values() for f in fs})} file(s).')
        unknown = []
        for (words, flags), files in sorted(inv.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            miss_w = [w for w in words if w not in docs_words and not re.fullmatch(r'\d+|[{<].*', w)]
            miss_f = [f for f in flags if f not in docs_flags]
            if miss_w or miss_f:
                unknown.append((words, flags, miss_w, miss_f, files))
        if not unknown:
            lines.append('No book tokens were missing from the man page (given the limits above).')
        else:
            problems += len(unknown)
            lines.append('')
            lines.append('| Invocation | Missing | Files |')
            lines.append('|---|---|---|')
            for words, flags, miss_w, miss_f, files in unknown[:80]:
                inv_s = ' '.join((tool,) + words + flags)
                miss = ', '.join(f'`{x}`' for x in list(miss_w) + list(miss_f))
                fl = ', '.join(f'`{f}`' for f in files[:4])
                if len(files) > 4:
                    fl += f' (+{len(files)-4})'
                lines.append(f'| `{inv_s}` | {miss} | {fl} |')
        lines.append('')
    body = '\n'.join(lines) + '\n'
    print(body)
    if a.out:
        open(a.out, 'w', encoding='utf-8').write(body)
    print(f'check-ceph-commands: {problems} row(s) to review against {release}', file=sys.stderr)
    if a.strict and problems:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
