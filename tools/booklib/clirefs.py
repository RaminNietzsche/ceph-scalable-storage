"""Shared helpers for the command-line reference (references/cli-reference.yaml).

Used by tools/build_site.py (the web appendix), tools/build_book.py (the
counts in the print pointer) and tools/check_cli_reference.py.
"""
from __future__ import annotations

import os
import re

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DATA = os.path.join(ROOT, 'references', 'cli-reference.yaml')
CHEATSHEET = os.path.join(ROOT, 'references', 'cheatsheet.yaml')
TAGS = ('both', 'code-only', 'docs-only', 'usage-only', 'no-usage')
TOOL_ORDER = ('ceph', 'rados', 'radosgw-admin', 'rbd', 'ceph-volume', 'cephfs-journal-tool')


def load(path: str | None = None) -> dict:
    with open(path or DATA, encoding='utf-8') as f:
        return yaml.load(f, Loader=getattr(yaml, 'CSafeLoader', yaml.SafeLoader))


def derive_tags(src: dict) -> list:
    """Tags implied by the in: {code, docs, usage} record (the generator uses the same rule)."""
    code, docs, usage = src.get('code'), src.get('docs'), src.get('usage')
    tags = ['both'] if code and docs else ['code-only'] if code else ['docs-only'] if docs else []
    if usage is True and not code:
        tags.append('usage-only')
    if usage is False and code:
        tags.append('no-usage')
    return tags


def _words(s: str) -> list:
    out = []
    for tok in s.split():
        if not re.fullmatch(r'[a-z][a-z0-9_-]*', tok):
            break
        out.append(tok)
    return out


def cheatsheet_links(data: dict, cs: dict | None = None) -> dict:
    """{(tool, command): [cheat-sheet entries]}: each cheat-sheet line goes to the longest
    reference command that prefixes it (aliases included); a line that is only a global
    option (ceph -s) goes to (tool, '@' + option)."""
    if cs is None:
        with open(CHEATSHEET, encoding='utf-8') as f:
            cs = yaml.safe_load(f)
    names, onames = {}, {}
    for t in data['tools']:
        om = {}
        for o in t.get('options', []):
            for n in [o['name']] + [a.strip() for a in (o.get('alias') or '').split(',') if a.strip()]:
                om.setdefault(n, o['name'])
        onames[t['id']] = om
        m = {}
        for c in t['commands']:
            if not c['in']['code']:
                continue
            m[c['name']] = c['name']
            for a in (c.get('alias') or '').split(','):
                a = a.strip()
                if a:
                    m.setdefault(a, c['name'])
        names[t['id']] = m
    out = {}
    for cat in cs['categories']:
        for e in cat['commands']:
            toks = e['cmd'].split()
            if not toks or toks[0] not in names:
                continue
            rest = toks[1:]
            # leading "-p <pool>" / "--pool=<pool>" pairs come before the command word
            while rest and rest[0].startswith('-'):
                if '=' not in rest[0] and len(rest) > 1 and rest[1].startswith('<'):
                    rest = rest[2:]
                elif len(rest) == 1 and rest[0] in onames[toks[0]]:
                    out.setdefault((toks[0], '@' + onames[toks[0]][rest[0]]), []).append(dict(e, cat=cat['id']))
                    rest = []
                else:
                    rest = rest[1:]
            w = _words(' '.join(rest))
            m = names[toks[0]]
            for k in range(len(w), 0, -1):
                key = ' '.join(w[:k])
                if key in m:
                    out.setdefault((toks[0], m[key]), []).append(dict(e, cat=cat['id']))
                    break
    return out


def counts(data: dict) -> tuple:
    """(commands, options) over every tool, from the stored summary."""
    s = data['meta']['summary']
    return sum(v['commands'] for v in s.values()), sum(v['options'] for v in s.values())
